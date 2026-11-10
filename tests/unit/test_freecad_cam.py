"""Machining admission, work-frame intent and independent finite NC reader."""
import copy
from pathlib import Path
import unittest
from schemaxis.adaptors.freecad import cam
from schemaxis.adaptors.freecad.cam_code import parse
from schemaxis.core.faults import SchemaxisError
ROOT=Path(__file__).resolve().parents[2]


def document():
    return {'version':cam.VERSION,'source':{'file':str(ROOT/'examples/schemaxis/freecad-import-step-bracket.step'),'units':'inch','expect':{'volume':10840,'bounds':[-20,20,-15,15,0,10],'centreOfMass':[-.808118,-.243542,5]}},'tool':{'diameter':3,'cuttingLength':20,'length':50,'shankDiameter':3,'rpm':10000,'feed':300,'plunge':100},'operations':[{'id':'top','operation':'faceStock','stepDown':1},{'id':'recess','operation':'pocket','floor':[0,0,3]}]}


class MachiningAdmission(unittest.TestCase):
    def fault(self,doc,code):
        with self.assertRaises(SchemaxisError) as caught:cam.plan(doc)
        self.assertEqual(caught.exception.fault.code,code)

    def test_setup_and_depths_follow_known_source_frame(self):
        d=document();original=copy.deepcopy(d);p=cam.plan(d);self.assertEqual(d,original);self.assertEqual(p['origin'],[0,0,12]);self.assertEqual(p['stockBounds'],[-20,20,-15,15,-12,0]);self.assertEqual(p['operations'][1]['finish'],-9);self.assertEqual(p['operations'][1]['start'],-2)

    def test_facing_and_holding_are_explicit(self):
        d=document();d['operations'].reverse();self.fault(d,'INVALID_MACHINING')
        for key in ('sides','bottom'):
            d=document();d['stock']={key:1};self.fault(d,'UNSUPPORTED_HOLDING')
        d=document();d['stock']={'top':0};d['operations']=d['operations'][1:];self.assertEqual(cam.plan(d)['operations'][0]['start'],0)

    def test_tool_reach_shank_and_cutting_data(self):
        for key,value in [('cuttingLength',5),('length',15),('shankDiameter',4)]:
            with self.subTest(key=key):d=document();d['tool'][key]=value;self.fault(d,'UNSUPPORTED_TOOL_REACH')
        for key,value in [('rpm',0),('feed',True),('plunge',None),('flutes',2.5)]:
            with self.subTest(key=key):d=document();d['tool'][key]=value;self.fault(d,'INVALID_MACHINING')

    def test_selector_and_order_fail_instead_of_native_reflection(self):
        for patch in ({'floor':[0,0,0]},{'floor':[0,0,10]},{'operation':'python'},{'stepOver':1},{'id':'top'},{'Face':'Face7'}):
            with self.subTest(patch=patch):d=document();d['operations'][1].update(patch);self.fault(d,'UNKNOWN_ARGUMENT' if 'Face' in patch else 'INVALID_MACHINING')
        d=document();d['setup']={'safe':6,'clearance':5};self.fault(d,'INVALID_MACHINING')
        d=document();d['quality']={'gougeVolume':100};self.fault(d,'INVALID_MACHINING')

    def test_planning_resources_do_not_reopen_deferred_sources(self):
        d=document();d['source']['file']='/gone/enclosure.step';self.assertEqual(cam.resources(d,{},'milling'),{})

    def test_schema_section_and_route_share_contract_without_native_import(self):
        from schemaxis.adaptors import registry
        from schemaxis.schema import export_schema
        self.assertEqual(export_schema('freecad',section='cam')['properties']['version']['const'],cam.VERSION)
        self.assertIsNotNone(registry.resolve(document()));self.assertEqual(cam.schema()['properties']['version']['const'],cam.VERSION)
        self.assertNotIn('FreeCAD',__import__('sys').modules)


class ProgramReader(unittest.TestCase):
    def program(self,moves='G0 Z5\nG0 X0 Y0\nG0 Z3\nG1 Z-1 F100\nG1 X5 F300\nG0 Z5\n'):
        return 'G17 G21 G54 G40 G80 G90 G91.1 G94 G61 G92.1\nM5\nM6 T1\nG43 H1\nM3 S10000\n'+moves+'M5\nM2\n'
    def read(self,s):return parse(s,document()['tool'],3)
    def fault(self,s,code):
        with self.assertRaises(SchemaxisError) as caught:self.read(s)
        self.assertEqual(caught.exception.fault.code,code)

    def test_real_modal_motion_and_feed_units(self):
        p=self.read(self.program());self.assertEqual(p['units'],'mm');self.assertEqual(p['motions'][1]['to'],[0,0,-1]);self.assertEqual(p['motions'][2]['feed'],300)

    def test_planar_arcs_retain_geometric_centre(self):
        s=self.program('G0 Z5\nG0 X0 Y0\nG1 Z-1 F100\nG2 X2 Y0 I1 J0 F300\nG0 Z5\n');p=self.read(s);self.assertEqual(p['motions'][1]['centre'],[1,0]);self.assertEqual(p['motions'][1]['code'],2)

    def test_posted_arc_radius_gate_is_stricter_than_persisted_rounding(self):
        s=self.program('G0 Z5\nG0 X0 Y0\nG1 Z-1 F100\nG2 X2.0000005 Y0 I1 J0 F300\nG0 Z5\n')
        with self.assertRaises(SchemaxisError) as caught:self.read(s)
        self.assertIn('arc endpoints do not share a radius',caught.exception.fault.message)
        self.assertTrue(parse(s,document()['tool'],3,arc_radius_tolerance=2e-6)['motions'])
        self.fault(s.replace('X2.0000005','X2.000003'),'INVALID_NC')

    def test_modal_conflicts_and_near_coincident_arc_do_not_mean_a_full_circle(self):
        for old,new in [('G21','G21 G21'),('G0 X0 Y0','G0 G1 X0 Y0'),('G43 H1','G43 G49 H1'),('M3 S10000','M3 M5 S10000')]:
            with self.subTest(new=new):self.fault(self.program().replace(old,new),'INVALID_NC')
        self.fault(self.program().replace('G1 X5 F300','G80 X5'),'INVALID_NC')
        moves='G0 Z5\nG0 X0 Y0\nG1 Z-1 F100\nG2 X0 Y0.00000001 I1 J0 F300\nG0 Z5\n'
        self.fault(self.program(moves),'UNSUPPORTED_TOOLPATH')
        self.assertTrue(self.read(self.program(moves.replace('Y0.00000001','Y0')))['motions'])

    def test_wrong_units_frames_hidden_cycles_and_injection_fail(self):
        for old,new in [('G21','G20'),('G90','G91'),('G54','G55'),('G94','G93'),('G43 H1','G43 H2'),('M6 T1','M6 T2'),('M3 S10000','M3 S20000'),('M3 S10000','M3'),('G1 X5 F300','G81 X5 Z-5 R2'),('M2','M2\nG0 X20'),('G0 Z5','G0 Z5 #1=3')]:
            with self.subTest(new=new):self.fault(self.program().replace(old,new),'INVALID_NC')

    def test_rapid_below_safe_plane_and_unqualified_ramp_fail(self):
        self.fault(self.program().replace('G1 X5 F300','G0 X5'),'UNSAFE_RAPID')
        self.fault(self.program().replace('G1 X5 F300','G1 X5 Z-2 F300'),'UNSUPPORTED_TOOLPATH')
        self.fault(self.program().replace('G1 X5 F300','G1 X5 F10'),'INVALID_NC')

    def test_entry_state_is_explicit_and_xy_rapid_cannot_raise_out_of_stock(self):
        for reset in ('G40','G80','G61','G92.1'):
            with self.subTest(reset=reset):self.fault(self.program().replace(reset,''),'INVALID_NC')
        self.fault(self.program().replace('M5\nM6','M6'),'INVALID_NC')
        self.fault(self.program().replace('G0 Z5\nG0 X0 Y0','G0 X0 Y0 Z5'),'UNSAFE_RAPID')
        self.fault(self.program().replace('G0 Z5\nG0 X0 Y0','G0 Z-1\nG0 Z5\nG0 X0 Y0'),'UNSAFE_RAPID')
        self.fault(self.program().replace('G1 X5 F300','G0 X5 Z5'),'UNSAFE_RAPID')


class SavedProgramBinding(unittest.TestCase):
    def test_saved_k_and_actual_motion_are_bound_before_replay(self):
        import tempfile
        from types import SimpleNamespace
        from xml.etree.ElementTree import Element
        from zipfile import ZipFile
        from schemaxis.adaptors.freecad.cam_checks import compare_saved_paths
        moves='G0 Z5\nG0 X0 Y0\nG0 Z3\nG1 Z-1 F100\nG1 X5 F300\nG0 Z5\n'
        program=ProgramReader().program(moves)
        with tempfile.TemporaryDirectory() as temporary:
            directory=Path(temporary);(directory/'program.ngc').write_text(program)
            saved=SimpleNamespace(child=lambda *a:Element('Path',{'file':'motion.bin'}))
            plan={'tool':document()['tool'],'setup':{'safe':3},'operations':[{'id':'top'}]}
            def write(text):
                with ZipFile(directory/'machining.FCStd','w') as archive:
                    archive.writestr('motion.bin','(Op_top)\n'+text)
            native=moves.replace('F100','F1.666667').replace('F300','F5.000000')
            write(native+'(K1 is only a comment)\n');compare_saved_paths(directory,plan,saved)
            write(native.replace('G1 X5','G1 X5 K0'));compare_saved_paths(directory,plan,saved)
            write(native.replace('G1 X5','G1 X5 K0.001'))
            with self.assertRaises(SchemaxisError) as caught:compare_saved_paths(directory,plan,saved)
            self.assertIn('nonzero K',caught.exception.fault.message)
            write(native.replace('G1 X5','G1 X5.000002'))
            with self.assertRaises(SchemaxisError) as caught:compare_saved_paths(directory,plan,saved)
            self.assertIn('motion differs',caught.exception.fault.message)


class NativeEnvelope(unittest.TestCase):
    def test_foreign_properties_extensions_expressions_and_restore_attributes_fail(self):
        from xml.etree.ElementTree import Element,SubElement
        from types import SimpleNamespace
        from schemaxis.adaptors.freecad.cam_tool_checks import closed
        from schemaxis.adaptors.freecad.cam_vocabulary import PROPERTY_TYPES,TRANSIENT
        root=Element('Document');objects=SubElement(root,'Objects');entry=SubElement(objects,'Object',{'name':'Source','type':'Part::Feature','id':'1'})
        data=SubElement(root,'ObjectData');obj=SubElement(data,'Object',{'name':'Source'});props=SubElement(obj,'Properties',{'Count':str(len(PROPERTY_TYPES['Source'])),'TransientCount':str(len(TRANSIENT['Source']))})
        properties={k:SubElement(props,'Property',{'name':k,'type':v}) for k,v in PROPERTY_TYPES['Source'].items()}
        for attrs in TRANSIENT['Source']:SubElement(props,'_Property',attrs)
        expressions=[];saved=SimpleNamespace(root=root,properties={'Source':properties},engine=lambda _:expressions)
        closed(saved,{'operations':[]})
        for typeid in ('App::PropertyXLink','App::PropertyPythonObject'):
            properties['Foreign']=Element('Property',{'name':'Foreign','type':typeid})
            with self.subTest(typeid=typeid),self.assertRaises(SchemaxisError):closed(saved,{'operations':[]})
            del properties['Foreign']
        extensions=SubElement(obj,'Extensions');SubElement(extensions,'Extension',{'type':'App::GroupExtensionPython'})
        with self.assertRaises(SchemaxisError):closed(saved,{'operations':[]})
        obj.remove(extensions);expressions.append(['Placement.Base.x','Foreign.Value'])
        with self.assertRaises(SchemaxisError):closed(saved,{'operations':[]})
        expressions.clear();entry.set('viewProvider','hostile.Module')
        with self.assertRaises(SchemaxisError):closed(saved,{'operations':[]})


class SavedProxyState(unittest.TestCase):
    def test_portable_profile_is_well_formed_and_has_only_reviewed_preferences(self):
        from xml.etree.ElementTree import fromstring
        from schemaxis.adaptors.freecad.cam_publication import PROFILE
        root=fromstring(PROFILE)
        self.assertEqual(root.tag,'FCParameters')
        node=root
        for name in ('Root','BaseApp','Preferences','Mod','CAM'):
            self.assertEqual(len(node),1);node=node[0]
            self.assertEqual((node.tag,node.attrib),('FCParamGroup',{'Name':name}))
        self.assertEqual([(c.tag,c.attrib) for c in node],[('FCFloat',{'Name':'LibAreaCurveAccuracy','Value':'0.00001'}),('FCParamGroup',{'Name':'Tools'}),('FCParamGroup',{'Name':'Migration'})])
        self.assertEqual([(c.tag,c.attrib,c.text) for c in node[1]],[('FCText',{'Name':'ToolPath'},'cam-assets')])
        self.assertEqual([(c.tag,c.attrib,c.text) for c in node[2]],[('FCText',{'Name':'OfferedToMigrateCAMAssets'},'v1-1')])

    def test_native_state_and_nested_mutations(self):
        import base64,json
        from xml.etree.ElementTree import Element,SubElement
        from schemaxis.adaptors.freecad.cam_proxies import check,tool_state
        expected=tool_state(dict(document()['tool'],flutes=2))
        def node(state):return Element('Python',{'module':'Path.Tool.toolbit.models.endmill','class':'ToolBitEndmill','encoded':'yes','value':base64.b64encode(json.dumps(state).encode()).decode()})
        def validate(value):check(value,'Path.Tool.toolbit.models.endmill','ToolBitEndmill',expected)
        validate(node(expected))
        for section,key,value in [('_obj_data','shape','../../hostile.fcstd'),('_shape_data','id','../../hostile'),('_obj_data','id','foreign-uuid')]:
            changed=copy.deepcopy(expected);changed[section][key]=value
            with self.subTest(section=section,key=key),self.assertRaises(ValueError):validate(node(changed))
        changed=copy.deepcopy(expected);changed['_obj_data']['parameter']['Diameter']='4.00 mm'
        with self.assertRaises(ValueError):validate(node(changed))
        changed=copy.deepcopy(expected);changed['_in_update']=0
        with self.assertRaises(ValueError):validate(node(changed))
        for attr,value in [('encoded','no'),('value','not-base64'),('extra','foreign')]:
            changed=node(expected);changed.set(attr,value)
            with self.subTest(attr=attr),self.assertRaises(ValueError):validate(changed)
        changed=node(expected);SubElement(changed,'Foreign')
        with self.assertRaises(ValueError):validate(changed)
        for raw in ('{"id":1,"id":2}','NaN','"'+('x'*9000)+'"'):
            changed=node(expected);changed.set('value',base64.b64encode(raw.encode()).decode())
            with self.subTest(raw=raw[:20]),self.assertRaises(ValueError):validate(changed)

    def test_fixed_class_states_are_exact(self):
        import base64,json
        from xml.etree.ElementTree import Element
        from schemaxis.adaptors.freecad.cam_proxies import check
        for state in (None,'Clone',{}):
            node=Element('Python',{'module':'reviewed','class':'Reviewed','encoded':'yes','value':base64.b64encode(json.dumps(state).encode()).decode()})
            check(node,'reviewed','Reviewed',state)
            node.set('value',base64.b64encode(b'{"extra":1}').decode())
            with self.assertRaises(ValueError):check(node,'reviewed','Reviewed',state)


if __name__=='__main__':unittest.main()
