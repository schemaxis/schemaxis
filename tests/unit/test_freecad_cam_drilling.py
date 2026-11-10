"""Independent physical tool/cycle intent and modal NC boundary controls."""
import copy
import math
import unittest
from schemaxis.adaptors.freecad import cam_tools,cam_drilling
from schemaxis.adaptors.freecad.cam_code2 import parse
from schemaxis.adaptors.freecad.cam_plan2 import plan
from schemaxis.core.faults import SchemaxisError


def tools():
    common={'kind':'flatEndmill','cuttingLength':20,'length':40,'flutes':2}
    return cam_tools.named([dict(common,id='face',diameter=6,shankDiameter=6,rpm=6000,feed=600,plunge=150),
                            dict(common,id='holes',diameter=4,shankDiameter=4,rpm=7000,feed=400,plunge=120)],14)


def program(cycles='G81 X-10 Y-8 Z-11 R3 F120\nG0 X10 Y8\nG81 X10 Y8 Z-11 R3 F120\n',mode='G98',initial=5):
    return ('G17 G21 G54 G40 G49 G80 G90 G91.1 G94 G61 G92.1\nM5\nM6 T2\nG43 H2\nM3 S7000\n'
            'G90\nG0 Z'+str(initial)+'\n'+mode+'\nG0 X-10 Y-8\n'+cycles+'G80\nG0 Z5\nM5\nM2\n')


class TypedTools(unittest.TestCase):
    def test_compiled_identity_is_geometry_bound_and_cutting_data_is_separate(self):
        a=tools();b=tools();self.assertEqual(a,b)
        self.assertEqual([t['number'] for t in a],[1,2]);self.assertEqual([t['controller'] for t in a],['Cutter0','Cutter1'])
        raw=[{k:v for k,v in t.items() if k in ('id','kind',*cam_tools.GEOMETRY,*cam_tools.CUTTING)} for t in a]
        raw[0]['feed']+=1;self.assertEqual(cam_tools.named(raw,14)[0]['nativeId'],a[0]['nativeId'])
        raw[0]['diameter']+=1;self.assertNotEqual(cam_tools.named(raw,14)[0]['nativeId'],a[0]['nativeId'])
        self.assertEqual(cam_tools.template_record(a[1])['nr'],2)

    def test_closed_tools_full_reach_and_operation_selection(self):
        a=tools();op={'tool':'holes'};self.assertEqual(cam_tools.selected(a,op,'op',explicit=True),a[1])
        for item in ({'tool':'missing'},{}):
            with self.subTest(item=item),self.assertRaises(SchemaxisError):cam_tools.selected(a,item,'op',explicit=True)
        with self.assertRaises(SchemaxisError):cam_tools.require_used(a,[op])
        cam_tools.require_used(a,[op,{'tool':'face'}])
        raw=[{k:v for k,v in a[0].items() if k in ('id','kind',*cam_tools.GEOMETRY,*cam_tools.CUTTING)}]
        for patch in ({'cuttingLength':10},{'shankDiameter':7},{'length':20},{'rpm':True},{'flutes':2.5},{'kind':'twistDrill'},{'nativeId':'foreign'}):
            with self.subTest(patch=patch),self.assertRaises(SchemaxisError):cam_tools.named([dict(raw[0],**patch)],14)
        with self.assertRaises(SchemaxisError):cam_tools.named(raw*2,14)


class TypedDrilling(unittest.TestCase):
    def test_whole_compiler_keeps_source_tool_and_order_authority(self):
        from test_freecad_cam import document
        d=document();raw=tools()
        d['tools']=[{k:v for k,v in t.items() if k in ('id','kind',*cam_tools.GEOMETRY,*cam_tools.CUTTING)} for t in raw]
        del d['tool'];d['operations'][0]['tool']='face';d['operations'][1]['tool']='face'
        d['operations'].insert(1,{'id':'bores','operation':'drill','tool':'holes','locations':{'kind':'grid','columns':2,'rows':2,'xPitch':20,'yPitch':16},'bottom':3,'cycle':{'kind':'peck','peck':2.5}})
        original=copy.deepcopy(d);p=plan(d)
        self.assertEqual(d,original);self.assertEqual(plan(d),p);self.assertEqual(p['version'],'schemaxis.freecad.cam.plan/2')
        from schemaxis.adaptors.freecad import cam
        import jsonschema
        self.assertEqual(cam.plan(d),p);jsonschema.validate(d,cam.schema())
        self.assertNotIn('tool',p);self.assertEqual([o['tool'] for o in p['operations']],['face','holes','face'])
        self.assertEqual(p['operations'][1]['finish'],-9);self.assertEqual(p['tools'],raw)
        for patch in ({'tool':original.get('tool',{})},{'tools':d['tools']+[d['tools'][0]]}):
            with self.subTest(patch=patch),self.assertRaises(SchemaxisError):plan(dict(d,**patch))
        del d['operations'][1]
        with self.assertRaises(SchemaxisError):plan(d)

    def test_reusable_source_frame_layouts_and_work_frame(self):
        self.assertEqual(cam_drilling.locations({'kind':'grid','columns':2,'rows':2,'xPitch':20,'yPitch':16},'p'),[[-10,-8],[-10,8],[10,-8],[10,8]])
        ring=cam_drilling.locations({'kind':'pitchCircle','count':4,'radius':7,'phase':30,'centre':[2,3]},'p')
        self.assertEqual(len(ring),4)
        for p in ring:self.assertAlmostEqual(math.dist(p,[2,3]),7)
        raw={'locations':{'kind':'explicit','centres':[[8,6],[-8,-6]]},'bottom':3,'cycle':{'kind':'peck','peck':2.5,'return':'retract'}}
        p=cam_drilling.operation(raw,tools()[1],[-20,20,-15,15,0,12],[1,2,14],{'safe':3,'clearance':5},'p')
        self.assertEqual(p['centres'],[[-9,-8],[7,4]]);self.assertEqual(p['finish'],-11);self.assertEqual(p['cycle']['code'],83)

    def test_all_locations_dimensions_and_cycle_choices_are_closed(self):
        for raw in ({'kind':'grid','columns':64,'rows':64,'xPitch':1,'yPitch':1},
                    {'kind':'grid','columns':True,'xPitch':1,'yPitch':1},
                    {'kind':'explicit','centres':[[1,2],[1,2]]},
                    {'kind':'explicit','centres':[[1,2]],'Base':'Edge7'},
                    {'kind':'pitchCircle','radius':2,'centre':[100000,0]}):
            with self.subTest(raw=raw),self.assertRaises(SchemaxisError):cam_drilling.locations(raw,'p')
        for raw in ({'kind':'peck'},{'kind':'drill','peck':1},{'kind':'dwell','dwell':0},
                    {'kind':'peck','peck':.001},{'kind':'chipBreak','peck':2,'dwell':1},
                    {'kind':'drill','return':'ClearanceHeight'},{'kind':'G81'}):
            with self.subTest(raw=raw),self.assertRaises(SchemaxisError):cam_drilling.compile_cycle(raw,-11,{'safe':3},'p')
        for kind,code in cam_drilling.CYCLES.items():
            raw={'kind':kind,**({'peck':2.5} if kind in ('peck','chipBreak') else {'dwell':.375} if kind=='dwell' else {})}
            self.assertEqual(cam_drilling.compile_cycle(raw,-11,{'safe':3},'p')['code'],code)

    def test_schema_cycle_choices_require_only_their_own_dimensions(self):
        import jsonschema
        from schemaxis.adaptors.freecad.cam import schema
        cycle=schema()['properties']['operations']['items']['oneOf'][1]['properties']['cycle']
        for value in ({},{'return':'retract'},{'kind':'drill'},
                      {'kind':'dwell','dwell':.375},{'kind':'peck','peck':.137},
                      {'kind':'chipBreak','peck':2.5},{'kind':'feedRetract'}):
            with self.subTest(value=value):jsonschema.validate(value,cycle)
        for value in ({'kind':'dwell'},{'kind':'peck'},{'kind':'drill','peck':2},
                      {'kind':'chipBreak','peck':2,'dwell':.5},{'kind':'feedRetract','dwell':.5},
                      {'dwell':.5},{'kind':'dwell','dwell':True},{'kind':'foreign'}):
            with self.subTest(value=value),self.assertRaises(jsonschema.ValidationError):jsonschema.validate(value,cycle)


class MultiToolProgram(unittest.TestCase):
    def read(self,text):return parse(text,tools(),3)
    def fault(self,text,code='INVALID_NC'):
        with self.assertRaises(SchemaxisError) as caught:self.read(text)
        self.assertEqual(caught.exception.fault.code,code)

    def test_initial_plane_comes_from_actual_pre_cycle_state(self):
        p=self.read(program());self.assertEqual([c['initial'] for c in p['cycles']],[5,5])
        self.assertEqual([c['returnZ'] for c in p['cycles']],[5,5])
        p=self.read(program(mode='G99'));self.assertEqual([c['returnZ'] for c in p['cycles']],[3,3])
        self.assertEqual([c['initial'] for c in p['cycles']],[5,3])
        p=self.read(program(initial=7.25));self.assertEqual(p['cycles'][0]['returnZ'],7.25)
        p=self.read(program().replace('G0 X10 Y8','G0 Z8\nG0 X10 Y8'))
        self.assertEqual([c['initial'] for c in p['cycles']],[5,8])
        p=self.read(program(initial=3).replace('R3','R4'))
        self.assertEqual(p['cycles'][0]['initial'],3);self.assertEqual(p['cycles'][0]['returnZ'],4)

    def test_peck_partial_bottom_and_controller_reentry_are_explicit(self):
        p=self.read(program('G83 X-10 Y-8 Z-5 R3 Q2.5 F120\n'))
        self.assertEqual([m['to'][2] for m in p['motions'] if m['code']==1],[.5,-2,-4.5,-5])
        self.assertEqual([m['to'][2] for m in p['motions'] if m['code']==0 and 'cycle' in m],[5,3,3,.754,3,-1.746,3,-4.246,5])
        self.assertEqual(p['cycles'][0]['peck'],2.5)
        self.assertEqual(p['dialect'],cam_drilling.DIALECT)

    def test_dwell_chip_break_and_feed_retract_have_distinct_meanings(self):
        p=self.read(program('G82 X-10 Y-8 Z-5 R3 P.375 F120\n'))
        self.assertEqual(p['cycles'][0]['dwell'],.375)
        p=self.read(program('G73 X-10 Y-8 Z-5 R3 Q2.5 F120\n'))
        self.assertEqual([m['to'][2] for m in p['motions'] if m['code']==0 and 'cycle' in m],[5,3,.754,-1.746,-4.246,5])
        p=self.read(program('G85 X-10 Y-8 Z-5 R3 F120\n'))
        self.assertEqual([m['to'][2] for m in p['motions'] if m['code']==1],[-5,3])

    def test_small_peck_controller_backoff_can_rise_above_r(self):
        for cycle,rapids in ((73,[5,3,3.154,3.054,2.954,5]),
                             (83,[5,3,3,3.154,3,3.054,3,2.954,5])):
            with self.subTest(cycle=cycle):
                p=self.read(program('G'+str(cycle)+' X-10 Y-8 Z2.65 R3 Q.1 F120\n'))
                feeds=[m['to'][2] for m in p['motions'] if m['code']==1]
                actual=[m['to'][2] for m in p['motions'] if m['code']==0 and 'cycle' in m]
                self.assertEqual(len(feeds),4);self.assertEqual(len(actual),len(rapids))
                for a,b in zip(feeds,[2.9,2.8,2.7,2.65]):self.assertAlmostEqual(a,b,12)
                for a,b in zip(actual,rapids):self.assertAlmostEqual(a,b,12)

    def test_active_return_switch_keeps_initial_until_g80_or_motion(self):
        active=('G99 G81 X-10 Y-8 Z-5 R3 F120\n'
                'G98 G81 X10 Y8 Z-5 R3 F120\n')
        p=self.read(program(active))
        self.assertEqual([(c['initial'],c['returnZ']) for c in p['cycles']],[(5,3),(5,5)])
        p=self.read(program(active.replace('G98 G81','G80\nG98 G81')))
        self.assertEqual([(c['initial'],c['returnZ']) for c in p['cycles']],[(5,3),(3,3)])
        p=self.read(program(active.replace('G98 G81','G0 Z7.25\nG98 G81')))
        self.assertEqual([(c['initial'],c['returnZ']) for c in p['cycles']],[(5,3),(7.25,7.25)])

    def test_return_to_first_tool_resets_length_rpm_and_feed(self):
        text=program().replace('M5\nM2','M5\nM6 T1\nG43 H1\nM3 S6000\nG0 X0 Y0\nG1 Z-1 F150\nG1 X5 F600\nG0 Z5\nM5\nM2')
        p=self.read(text);self.assertEqual([c['tool'] for c in p['toolChanges']],['holes','face'])
        self.assertEqual([m['tool'] for m in p['motions'] if m['code']==1],['holes','holes','face','face'])
        for old,new in [('G43 H1','G43 H2'),('M3 S6000','M3'),('G1 Z-1 F150','G1 Z-1'),('G1 X5 F600','G1 X5 F400')]:
            with self.subTest(new=new):self.fault(text.replace(old,new))

    def test_refreshed_program_cannot_hide_cycles_modal_state_or_wrong_tools(self):
        base=program()
        for old,new in [('G21','G20'),('G90','G91'),('G43 H2','G43 H1'),('M6 T2','M6 T3'),
                        ('M3 S7000','M3 S6000'),('F120','F150'),('G81 X10','X10'),
                        ('G81 X10','G81 X1e300'),('G81 X10','G81 X300000'),
                        ('G81 X10','G81 G83 X10'),('G81 X10','G81 X10 Q2'),
                        ('M2','M2\nG0 Z8'),('G0 Z5','G0 Z5 #1=3'),
                        ('M6 T2','T2'),('G98','G98 G99'),('G80\nG0 Z5','G81 X1 Y2 Z-4 R3 F120\n'),
                        ('G0 Z5\nM5','G0 Z-5\nM5')]:
            with self.subTest(new=new):self.fault(base.replace(old,new),'UNSAFE_RAPID' if 'Z-5\nM5' in new else 'INVALID_NC')
        self.fault(base.replace('R3','R2'),'UNSAFE_RAPID')
        self.fault(base.replace('G81 X-10','G0 X-10'),'INVALID_NC')
        self.fault(base.replace('G81 X-10','G81 X-10 Z-11'),'INVALID_NC')

    def test_cycles_are_bounded_and_ordinary_rapid_rules_stay_strict(self):
        self.fault(program('G83 X-10 Y-8 Z-100 R3 Q.001 F120\n'),'RESOURCE_LIMIT')
        for words in ('Q0','Q-1','Q1001','P1'):
            self.fault(program('G83 X-10 Y-8 Z-5 R3 '+words+' F120\n'))
        text=program('G81 X-10 Y-8 Z-5 R3 F120\n').replace('G80\nG0 Z5','G80\nG1 Z-1 F120\nG0 X5 Z5')
        self.fault(text,'UNSAFE_RAPID')


class PhysicalFootprints(unittest.TestCase):
    def test_large_shallow_and_small_deep_same_centre_are_distinct_sweeps(self):
        from schemaxis.adaptors.freecad.cam_tracks2 import tracks
        table=tools();table[0]['diameter']=6;table[1]['diameter']=2
        replay={'motions':[{'code':1,'from':[2,3,5],'to':[2,3,-2],'tool':'face'},
                           {'code':1,'from':[2,3,5],'to':[2,3,-8],'tool':'holes'},
                           {'code':1,'from':[2,3,-5],'to':[2,3,-8],'tool':'holes'},
                           {'code':0,'from':[2,3,-8],'to':[2,3,5],'tool':'holes'}]}
        paths,vertical=tracks(replay,table);self.assertEqual(paths,{})
        self.assertEqual(vertical,{('face',2,3):-2,('holes',2,3):-8})
        # For these concentric tools the exact cut section is the largest
        # active disc. It is pi*3^2 above -2, then pi*1^2 down to -8.
        radii={t['id']:t['diameter']/2 for t in table}
        def area(z):return math.pi*max(radii[k[0]]**2 for k,bottom in vertical.items() if bottom<=z)
        self.assertAlmostEqual(area(-1),9*math.pi);self.assertAlmostEqual(area(-7),math.pi)
        self.assertAlmostEqual(area(-1)*2+area(-7)*6,24*math.pi)

    def test_identical_horizontal_paths_keep_their_tool_and_depth(self):
        from schemaxis.adaptors.freecad.cam_tracks2 import tracks
        replay={'motions':[{'code':1,'from':[0,0,-2],'to':[5,0,-2],'tool':'face'},
                           {'code':1,'from':[5,0,-7],'to':[0,0,-7],'tool':'holes'}]}
        paths,vertical=tracks(replay,tools());self.assertEqual(vertical,{})
        self.assertEqual(sorted((m['tool'],z) for z,m in paths.values()),[('face',-2),('holes',-7)])


class SavedEvidence(unittest.TestCase):
    def test_complete_local_dictionary_binds_unused_values_owners_and_multiplicity(self):
        from xml.etree import ElementTree as E
        from schemaxis.adaptors.freecad.cam_state2 import postfix_inventory
        def root(identity):
            return E.fromstring(f'<Document><Objects><Object name="A" id="{identity}"/></Objects>'
                '<StringHasher2 file="table"/><ObjectData><Object name="A"><Properties>'
                '<Property name="Shape"><ElementMap2 file="map"/></Property></Properties></Object></ObjectData></Document>')
        def members(owner,postfixes,sid=1):
            payload=('BeginElementMap v1\n1 PostfixCount '+str(len(postfixes))+'\n'+'\n'.join(postfixes)+'\n\nMapCount 1\n\n'
                'ElementMap 1 1 1\n\nEdge\n\nChildCount 0\n\nNameCount 1\n;;:H'+format(owner,'x')+',E.0 0\n\nEndMap\n').encode()
            return {'map':payload,'table':('StringTableStart v1 1\n'+format(sid,'x')+'.0 0:retained\n').encode()}
        original=postfix_inventory(members(7,['Edge','#1',';:H7,F']),root(7))
        self.assertEqual(original,postfix_inventory(members(9,[';:H9,F','Edge','#3'],3),root(9),{9:7}))
        for changed in (['Edge','#1',';:H7,F','unused'],['Edge','#1',';:H7,F','Edge'],['Edge','#1']):
            with self.subTest(changed=changed):self.assertNotEqual(original,postfix_inventory(members(7,changed),root(7)))
        for changed in (['Edge',';:H7fffffff,F'],['Edge','#7fffffff']):
            with self.subTest(changed=changed),self.assertRaises(ValueError):postfix_inventory(members(7,changed),root(7))

    def test_semantic_material_counters_remain_exact_without_metric_changes(self):
        from schemaxis.adaptors.freecad.cam_checks2 import counts,numeric
        from schemaxis.adaptors.freecad.cam_evidence2 import same
        a={'sweeps':1000000,'tracks':2,'motions':26,'slabs':[{'footprints':1}]}
        b=copy.deepcopy(a);self.assertTrue(same(counts(a),counts(b)))
        b['sweeps']+=1;self.assertFalse(same(counts(a),counts(b)))
        for value in (2.0,True,-1):
            b=copy.deepcopy(a);b['tracks']=value
            with self.subTest(value=value),self.assertRaises(ValueError):counts(b)
        self.assertTrue(numeric(.000001,0.0))
        self.assertFalse(numeric(.001,0.0))

    def test_exact_recipe_types_and_closed_bounded_json(self):
        import tempfile
        from pathlib import Path
        from schemaxis.adaptors.freecad.cam_evidence2 import same,read
        self.assertTrue(same({'a':[1,2.0,True,None]},{'a':[1,2.0,True,None]}))
        for a,b in ((True,1),(1,1.0),({'a':[True]},{'a':[1]}),({'a':[1]},{'a':[1,2]})):
            self.assertFalse(same(a,b))
        with tempfile.TemporaryDirectory() as temporary:
            p=Path(temporary)/'receipt.json'
            for raw in ('{"value":1,"value":2}','{"value":NaN}','{"value":Infinity}','{"value":1e999}'):
                p.write_text(raw)
                with self.assertRaises(ValueError):read(p)
            p.write_text('{"value":1}')
            self.assertEqual(read(p),{'value':1})
            with self.assertRaises(ValueError):read(p,1)

    def test_native_path_serialization_has_exact_signed_decimal_binding(self):
        from schemaxis.adaptors.freecad.cam_paths2 import readback
        expected=[{'name':'G1','parameters':{'X':20.1,'F':2.5}}]
        self.assertTrue(readback([{'name':'G1','parameters':{'X':20.099999926673583,'F':2.5}}],expected))
        for value in (20.100001,True,float('nan')):
            self.assertFalse(readback([{'name':'G1','parameters':{'X':value,'F':2.5}}],expected))
        self.assertFalse(readback([{'name':'G1','parameters':{'X':0.0}}],[{'name':'G1','parameters':{'X':-0.0}}]))

    def test_posted_cycles_bind_each_hole_strategy_return_and_word_precision(self):
        from schemaxis.adaptors.freecad.cam_cycles2 import validate
        replay=parse(program(),tools(),3)
        spec={'id':'bores','operation':'drill','tool':'holes','centres':[[-10,-8],[10,8]],'finish':-11,
              'cycle':{'code':81,'return':'initial','retract':3,'dwell':0,'peck':0}}
        p={'operations':[spec]};validate(p,replay)
        for field,value in (('centre',[-10,-8]),('centre',[10]),('tool','face'),('bottom',-10.999999),('return',99),('dwell',True),('peck',2.5)):
            changed=copy.deepcopy(replay);changed['cycles'][1][field]=value
            with self.subTest(field=field),self.assertRaises(SchemaxisError):validate(p,changed)
        changed=copy.deepcopy(replay);changed['cycles'].pop()
        with self.assertRaises(SchemaxisError):validate(p,changed)


if __name__=='__main__':unittest.main()
