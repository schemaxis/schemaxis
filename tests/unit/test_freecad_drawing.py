"""Host admission of drawing intent, source ownership and public route assets."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from zipfile import ZipFile
from schemaxis.adaptors.freecad import drawing
from schemaxis.core.faults import SchemaxisError
ROOT=Path(__file__).resolve().parents[2]


def document():
    return {'version':drawing.VERSION,'source':{'file':str(ROOT/'examples/schemaxis/freecad-import-step-bracket.step'),'units':'inch','expect':{'volume':10840,'bounds':[-20,20,-15,15,0,10],'centreOfMass':[-.808118,-.243542,5]}},'sheet':{'title':'Supplier bracket','scale':'fit'},'views':['front','top','right','isometric'],'dimensioning':[{'id':'width','view':'front','type':'overallWidth'}]}


class DrawingAdmission(unittest.TestCase):
    def test_native_zero_sign_rewrite_retains_all_nonzero_values_and_precision(self):
        from schemaxis.adaptors.freecad.drawing_checks import checked_brep
        original=b'2 0.00000000000000000 -0.00000000000000000 2.50000000000000000\n'
        saved=b'2 -0.00000000000000000 0.00000000000000000 2.50000000000000000\n'
        self.assertEqual(checked_brep(original),checked_brep(saved))
        for altered in (saved.replace(b'2.50000000000000000',b'2.50000000000000001'),
                        saved.replace(b'-0.00000000000000000',b'-0.00000000000000001'),
                        saved.replace(b'-0.00000000000000000',b'-0.0000000000000000'),
                        saved.replace(b'-0.00000000000000000',b'0e0')):
            self.assertNotEqual(checked_brep(original),checked_brep(altered))

    def fault(self,doc,code='INVALID_DRAWING'):
        with self.assertRaises(SchemaxisError) as raised:drawing.plan(doc)
        self.assertEqual(raised.exception.fault.code,code)

    def test_standard_sheet_has_inspectable_native_intent(self):
        p=drawing.plan(document());self.assertEqual(p['source']['format'],'STEP');self.assertEqual(p['source']['sourceUnits'],'inch');self.assertEqual(p['dimensions'][0]['expected'],40)
        self.assertGreater(p['sheet']['scale'],0);self.assertEqual(p['views'][0]['position'],[84.25,147.5]);self.assertGreater(p['dimensions'][0]['position'][1],p['views'][0]['position'][1])

    def test_scale_and_projection_variation(self):
        d=document();d['views']=['rear','bottom','left'];d['dimensioning']=[];d['sheet'].update(size='A3',scale=.5)
        p=drawing.plan(d);self.assertEqual(p['sheet']['width'],420);self.assertEqual(p['views'][0]['right'],[-1,0,0])

    def test_point_and_mounting_centre_intent(self):
        d=document();d['dimensioning']=[{'id':'mount','view':'top','type':'horizontal','from':{'point':[-20,-15,0]},'to':{'point':[-9,-6,0],'on':'circleCentre','radius':3}}]
        d['dimensioning'].append({'id':'width','view':'front','type':'overallWidth'})
        p=drawing.plan(d)['dimensions'][0];self.assertEqual(p['expected'],11);self.assertEqual(p['from']['projected'],[-20,-15]);self.assertEqual(p['to']['projected'],[-9,-6])

    def test_distance_is_projected_and_uses_view_frame(self):
        d=document();d['dimensioning']=[{'id':'diagonal','view':'front','type':'distance','from':{'point':[0,5,0]},'to':{'point':[3,100,4]}}]
        self.assertEqual(drawing.plan(d)['dimensions'][0]['expected'],5)

    def test_all_authored_names_are_finite(self):
        for field,value in [('views',[]),('views',['front','front']),('views',['unsupported']),('notes',['a\nb']),('notes',['a']*5)]:
            with self.subTest(field=field,value=value):d=document();d[field]=value;self.fault(d)

    def test_wrong_units_are_distinct(self):
        d=document();d['source']['units']='mm';self.fault(d,'UNIT_MISMATCH')
        d=document();d['source']['units']='feet';self.fault(d,'UNSUPPORTED_UNITS')

    def test_numerical_types_and_ranges(self):
        for value in (True,None,float('nan'),float('inf'),0,-1):
            with self.subTest(value=value):d=document();d['source']['expect']['volume']=value;self.fault(d,'INVALID_JSON' if type(value) is float and not __import__('math').isfinite(value) else 'INVALID_CAD_SOURCE')
        for value in ([0,0,0,10,0,5],[0,10,0,5,True,6],[0,10]):
            with self.subTest(bounds=value):d=document();d['source']['expect']['bounds']=value;self.fault(d,'INVALID_CAD_SOURCE')

    def test_default_dimension_lanes_are_distinct_and_reduce_fit(self):
        d=document();d['dimensioning']=[{'id':'width','view':'top','type':'overallWidth'},{'id':'wall','view':'top','type':'horizontal','from':{'point':[-20,-15,10]},'to':{'point':[-18,-13,10]}},{'id':'mount','view':'top','type':'horizontal','from':{'point':[-20,-15,10]},'to':{'point':[-10,-5,10]}}]
        p=drawing.plan(d);positions=[x['position'] for x in p['dimensions']]
        ys=sorted(q[1] for q in positions);self.assertEqual([round(ys[i+1]-ys[i],8) for i in range(2)],[10,10]);self.assertGreater(positions[0][1],positions[1][1])
        self.assertTrue(all(35<=q[1]<=200 for q in positions));self.assertLess(p['sheet']['scale'],drawing.plan(document())['sheet']['scale'])

    def test_overflow_is_refused(self):
        d=document();d['sheet']['scale']=10;self.fault(d,'DRAWING_OVERFLOW')
        d=document();d['dimensioning'][0]['position']=[0,0];self.fault(d,'DRAWING_OVERFLOW')

    def test_circular_labels_have_distinct_leader_directions(self):
        d=document();d['dimensioning']=[{'id':'diameter','view':'top','type':'diameter','radius':3},{'id':'radius','view':'top','type':'radius','radius':3}]
        p=drawing.plan(d);view=next(v for v in p['views'] if v['id']=='top')
        positions={item['id']:item['position'] for item in p['dimensions']}
        self.assertLess(positions['diameter'][0],view['position'][0])
        self.assertGreater(positions['radius'][0],view['position'][0])
        for point in positions.values():self.assertGreater(point[1],view['position'][1])
        d['dimensioning'].reverse()
        self.assertEqual(positions,{item['id']:item['position'] for item in drawing.plan(d)['dimensions']})

    def test_dimension_semantics(self):
        variants=[{'type':'diameter'},{'view':'isometric'},{'id':'front'},{'radius':3},{'view':'missing'},{'type':'horizontal','from':{'point':[0,0,0]},'to':{'point':[0,0,0]}}]
        for patch in variants:
            with self.subTest(patch=patch):d=document();d['dimensioning'][0].update(patch);self.fault(d)

    def test_missing_source_and_bounded_archive(self):
        d=document();d['source']['file']='/nonexistent/drawing.step';self.fault(d,'RESOURCE_NOT_FOUND')
        with tempfile.TemporaryDirectory() as t:
            path=Path(t)/'bad.FCStd'
            with ZipFile(path,'w') as z:z.writestr('Document.xml','<!DOCTYPE Document [<!ENTITY x "boom">]><Document/>')
            d=document();d['source'].update(file=str(path),object='Stock',units='mm');self.fault(d,'UNSUPPORTED_SOURCE')

    def test_fcstd_geometry_selection_never_loads_proxy(self):
        with tempfile.TemporaryDirectory() as t:
            path=Path(t)/'geometry.FCStd'
            xml='''<Document><Objects><Object name="Solid" type="PartDesign::FeaturePython"/></Objects><ObjectData><Object name="Solid"><Properties><Property name="Label" type="App::PropertyString"><String value="enclosure"/></Property><Property name="Shape" type="Part::PropertyPartShape"><Part file="shape.brp"/><ElementMap/></Property><Property name="Proxy" type="App::PropertyPythonObject"><Python value="never deserialise"/></Property></Properties></Object></ObjectData></Document>'''
            with ZipFile(path,'w') as z:z.writestr('Document.xml',xml);z.writestr('shape.brp','\nCASCADE Topology V1\nstatic shape')
            d=document();d['source'].update(file=str(path),object='enclosure',units='mm');p=drawing.plan(d)
            self.assertEqual(p['source']['object'],'Solid');self.assertEqual(p['source']['selector'],'enclosure');self.assertIn('brepSha256',p['source'])
            d['source']['object']='missing';self.fault(d,'UNSUPPORTED_SOURCE')

    def test_retained_sources_do_not_reopen_original(self):
        with tempfile.TemporaryDirectory() as t:
            d=document();p=drawing.plan(d);capture=Path(t)/p['source']['capture'];capture.write_bytes(Path(d['source']['file']).read_bytes())
            original=Path(t)/'gone.step';d['source']['file']=str(original)
            p=drawing._native_plan(d,captured=capture);(Path(t)/'plan.json').write_text(json.dumps(p))
            self.assertEqual(drawing.retainedInputs(t,d),{str(original):p['source']['sha256']})
            capture.write_text('mutated source')
            with self.assertRaises(SchemaxisError):drawing.retainedInputs(t,d)

    def test_resources_can_use_saved_document_without_original(self):
        d=document();d['source']['file']='/gone/supplier.step';self.assertEqual(drawing.resources(d,{},'sheet'),{})

    def test_wrapped_title_is_centred_in_reserved_strip(self):
        d=document();d['sheet']['title']='Parametric enclosure - manufacturing drawing';p=drawing.plan(d)
        self.assertGreaterEqual(len(p['annotations']['Title']['text']),3)
        self.assertEqual(p['annotations']['Title']['position'][1],17.5)

    def test_brep_mask_keeps_geometric_and_other_flag_bytes(self):
        from schemaxis.adaptors.freecad.drawing_checks import checked_brep
        self.assertEqual(checked_brep(b'Co\n\n1100000\nSo\n\n1100000\n'),b'Co\n\n0100000\nSo\n\n0100000\n')
        self.assertNotEqual(checked_brep(b'Co\n\n1101000\n'),checked_brep(b'Co\n\n1100000\n'))
        self.assertEqual(checked_brep(b'point 1100000\n'),b'point 1100000\n')

    def test_schema_and_catalogue_have_no_native_imports(self):
        from schemaxis.adaptors import registry
        schema=drawing.schema();self.assertEqual(schema['properties']['version']['const'],drawing.VERSION)
        self.assertIsNotNone(registry.resolve(document()))
        self.assertNotIn('FreeCAD',__import__('sys').modules)

    def test_publication_uses_only_private_finite_native_dispatch(self):
        from schemaxis.adaptors.freecad import gui_process,gui_native
        for family,stage in (('drawing','gui_finish'),('drawing','reopen'),('drawing_native','publish')):
            with self.subTest(family=family,stage=stage):
                with self.assertRaises(ValueError):gui_process.run('/unused','/bin/true',stage,family=family)
                with self.assertRaises(ValueError):gui_native.entry('/unused',stage,family)
        with patch.object(gui_process,'run',return_value={'isolation':{'private':True}}) as private:
            result=drawing._publish(Path('/unused'),'/bin/true',10)
            private.assert_called_once_with(Path('/unused'),'/bin/true','publish',timeout=10,family='drawing')
            self.assertTrue(result['isolation']['private'])


if __name__=='__main__':unittest.main()
