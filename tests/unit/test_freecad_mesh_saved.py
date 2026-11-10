"""Saved Mesh object roles and complete records bind to trusted reconstruction."""
import copy,unittest
from xml.etree import ElementTree as E
from schemaxis.adaptors.freecad.mesh_verify import compare_xml,source_brep_matches


def fixture():
    root=E.Element('Document',SchemaVersion='4',ProgramVersion='fixed',FileVersion='1',StringHasher='1')
    E.SubElement(root,'StringHasher',saveall='0',threshold='0',count='0')
    p=E.SubElement(root,'Properties',Count='2',TransientCount='0')
    c=E.SubElement(p,'Property',name='CreationDate',type='App::PropertyString',status='16777217');E.SubElement(c,'String',value='2026-11-05T00:00:00-05:00')
    c=E.SubElement(p,'Property',name='Uid',type='App::PropertyUUID',status='16777217');E.SubElement(c,'Uuid',value='00000000-0000-0000-0000-000000000001')
    o=E.SubElement(root,'Objects',Count='1',Dependencies='1');E.SubElement(o,'ObjectDeps',Name='N0',Count='0');E.SubElement(o,'Object',name='N0',type='Part::Feature',id='1')
    d=E.SubElement(root,'ObjectData',Count='1');o=E.SubElement(d,'Object',name='N0');p=E.SubElement(o,'Properties',Count='2',TransientCount='1')
    E.SubElement(p,'_Property',name='_ElementMapVersion',type='App::PropertyString',status='234881024')
    c=E.SubElement(p,'Property',name='Label',type='App::PropertyString',status='134217728');E.SubElement(c,'String',value='mesh')
    c=E.SubElement(p,'Property',name='Placement',type='App::PropertyPlacement',status='8388608')
    E.SubElement(c,'PropertyPlacement',Px='0',Py='0',Pz='0',Q0='0',Q1='0',Q2='0',Q3='1',A='0',Ox='0',Oy='0',Oz='1')
    return root


class SavedMesh(unittest.TestCase):
    def test_import_observations_bind_frame_and_independent_box_material(self):
        from schemaxis.adaptors.freecad.mesh_verify import verify_observation
        from schemaxis.core.faults import SchemaxisError
        facts={'facets':12,'volume':6000,'area':2200,'bounds':[0,10,0,20,0,30],'centreOfMass':[5,10,15]}
        node={'id':'casting','frame':{'worldFromFile':[[0,-1,0],[1,0,0],[0,0,1]],'translation':[20,-5,7]},'source':facts}
        value={'placement':[0,-1,0,20,1,0,0,-5,0,0,1,7],
               'fileFrame':{'valid':True,'solids':1,'faces':12,'shellsClosed':[True],**{k:v for k,v in facts.items() if k!='facets'}}}
        verify_observation(node,value,'unchanged')
        for change in ('placement','volume','faces','open-shell','solids'):
            altered=copy.deepcopy(value)
            if change=='placement':altered['placement'][3]+=1
            elif change=='volume':altered['fileFrame']['volume']+=2
            elif change=='faces':altered['fileFrame']['faces']+=1
            elif change=='open-shell':altered['fileFrame']['shellsClosed']=[False]
            else:altered['fileFrame']['solids']=2
            with self.subTest(change=change):
                with self.assertRaises(SchemaxisError) as error:verify_observation(node,altered,'changed')
                self.assertEqual(error.exception.fault.code,'VERIFICATION_FAILED')

    def test_checked_face_cache_bit_is_not_a_geometry_or_general_flag_exception(self):
        reference=(b'\nCASCADE Topology V1, (c) Matra-Datavision\n'
                   b'Locations 0\nSurfaces 1\n1 0 0 0 0 0 1 1 0 0\n'
                   b'TShapes 2\nVe\n0.000000100000000\n0 0 0\n0 0\n\n0101100\n*\n'
                   b'Fa\n0  0.000000100000000 1 0\n\n0101000\n+1 0 *\n\n+2 0\n')
        checked=reference.replace(b'0101000',b'0111000')
        self.assertTrue(source_brep_matches(reference,checked))
        self.assertFalse(source_brep_matches(checked,reference))
        signed=reference.replace(b'1 0 0 0 0 0 1',b'1 -0.000 0 0 0 0 1')
        self.assertNotEqual(signed,reference)
        # The producer can contain decimal negative zero; native serialization
        # can drop its sign at the same token while also setting Face.Checked.
        self.assertTrue(source_brep_matches(signed,signed.replace(b'-0.000',b'0.000').replace(b'0101000',b'0111000')))
        for bit in (0,1,3,4,5,6):
            flags=bytearray(b'0111000');flags[bit]=ord('0') if flags[bit]==ord('1') else ord('1')
            with self.subTest(bit=bit):self.assertFalse(source_brep_matches(reference,checked.replace(b'0111000',bytes(flags))))
        for mutated in (checked.replace(b'0101100',b'0111100'),
                        checked.replace(b'1 0 *',b'2 0 *'),
                        checked.replace(b'0 0 0 0 0 1',b'1 0 0 0 0 1'),
                        checked+b'unused',checked.replace(b'V1,',b'V2,')):
            self.assertFalse(source_brep_matches(reference,mutated))

    def test_native_dates_uuid_ids_and_only_touched_status_can_change(self):
        expected=fixture();actual=copy.deepcopy(expected)
        actual.find('.//Objects/Object').set('id','7')
        actual.find("./Properties/Property[@name='CreationDate']/String").set('value','2026-11-05T02:30:01-05:00')
        actual.find("./Properties/Property[@name='Uid']/Uuid").set('value','00000000-0000-0000-0000-000000000002')
        actual.find(".//ObjectData/Object/Properties/Property[@name='Label']").set('status','134217729')
        compare_xml(actual,expected)

    def test_omitted_zero_property_status_and_touched_are_equivalent_but_roles_are_not(self):
        expected=fixture();p=expected.find("./ObjectData/Object/Properties/Property[@name='Label']");p.attrib.pop('status')
        for status in ('0','1'):
            actual=copy.deepcopy(expected);actual.find("./ObjectData/Object/Properties/Property[@name='Label']").set('status',status)
            compare_xml(actual,expected)
        actual=copy.deepcopy(expected);actual.find("./ObjectData/Object/Properties/Property[@name='Label']").set('status','4')
        with self.assertRaises(ValueError):compare_xml(actual,expected)

    def test_foreign_transient_property_extension_and_persistence_roles_refused(self):
        expected=fixture()
        for change in ('transient','extension','role','extra-attribute','expression','redundant-angle'):
            actual=copy.deepcopy(expected);obj=actual.find('./ObjectData/Object');p=obj.find('Properties')
            if change=='transient':E.SubElement(p,'_Property',name='Marker',type='App::PropertyPythonObject',status='0')
            elif change=='extension':E.SubElement(obj,'Extensions',Count='1')
            elif change=='role':p.find("Property[@name='Label']").set('status','134217732')
            elif change=='extra-attribute':p.find("Property[@name='Label']").set('ro','1')
            elif change=='expression':E.SubElement(p,'Property',name='ExpressionEngine',type='App::PropertyExpressionEngine')
            else:p.find('.//PropertyPlacement').set('A','1')
            with self.subTest(change=change):
                with self.assertRaises(ValueError):compare_xml(actual,expected)

    def test_nonfinite_placement_uuid_date_and_unbound_hasher_changes_refused(self):
        expected=fixture()
        for change in ('nonfinite','uuid','date','hasher'):
            actual=copy.deepcopy(expected)
            if change=='nonfinite':actual.find('.//PropertyPlacement').set('Px','nan')
            elif change=='uuid':actual.find('.//Uuid').set('value','untrusted')
            elif change=='date':actual.find("./Properties/Property[@name='CreationDate']/String").set('value','untrusted')
            else:actual.find('StringHasher').set('count','1')
            with self.subTest(change=change):
                with self.assertRaises(ValueError):compare_xml(actual,expected)
