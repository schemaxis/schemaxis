"""Ordered parser transition witnesses, with legacy replay kept exact."""
import unittest
from test_freecad_cam_drilling import program,tools
from schemaxis.adaptors.freecad.cam_code2 import parse


class OrderedEvents(unittest.TestCase):
    def test_lower_ordinary_rapids_require_complete_ordered_physical_replay(self):
        from schemaxis.core.faults import SchemaxisError
        code=program().replace('G80\nG0 Z5','G80\nG1 Z-1 F120\nG0 X5\nG0 Z-2\nG0 Z5')
        with self.assertRaises(SchemaxisError) as caught:parse(code,tools(),3)
        self.assertEqual(caught.exception.fault.code,'UNSAFE_RAPID')
        replay=parse(code,tools(),3,ordered=True)
        lower=[m for m in replay['motions'] if m['code']==0 and min(m['from'][2],m['to'][2])<0 and 'cycle' not in m]
        self.assertEqual([m['to'] for m in lower],[[5.,8.,-1.],[5.,8.,-2.],[5.,8.,5.]])
        self.assertEqual([e['motion'] for e in replay['events'] if 'motion' in e],list(range(len(replay['motions']))))
        # An unobserved descent before XY is known cannot vanish from the
        # physical event inventory and later reappear as a positioned event.
        unknown=program().replace('G0 Z5\nG98','G0 Z5\nG0 Z-1\nG98')
        with self.assertRaises(SchemaxisError) as caught:parse(unknown,tools(),3,ordered=True)
        self.assertEqual(caught.exception.fault.code,'UNSAFE_RAPID')

    def test_legacy_replay_stays_identical_and_first_pose_has_current_tool(self):
        code=program();legacy=parse(code,tools(),3);ordered=parse(code,tools(),3,ordered=True)
        events=ordered.pop('events');self.assertEqual(ordered,legacy)
        self.assertEqual(events[0],{'toolChange':{'tool':'holes','position':None}})
        self.assertEqual(events[1],{'positioned':{'tool':'holes','position':[-10.,-8.,5.]}})
        self.assertEqual([e['motion'] for e in events if 'motion' in e],list(range(len(legacy['motions']))))

    def test_tool_return_gets_new_full_pose_check_and_expanded_pecks_stay_ordered(self):
        first=program(cycles='G83 X-10 Y-8 Z-1 R3 Q.193 F120\n')
        code=first.replace('M2\n','M6 T1\nG43 H1\nM3 S6000\nG1 Z4 F150\nG0 Z5\nM5\nM6 T2\nG43 H2\nM3 S7000\nG1 Z4 F120\nG0 Z5\nM5\nM2\n')
        replay=parse(code,tools(),3,ordered=True);events=replay['events']
        changes=[e['toolChange'] for e in events if 'toolChange' in e]
        self.assertEqual([e['tool'] for e in changes],['holes','face','holes'])
        self.assertEqual([e['position'] for e in changes[1:]],[[-10.,-8.,5.],[-10.,-8.,5.]])
        self.assertGreater(len(replay['motions']),60)
        self.assertEqual([e['motion'] for e in events if 'motion' in e],list(range(len(replay['motions']))))
        after=[e for e in events if 'toolChange' in e or 'motion' in e]
        for index,event in enumerate(after):
            if 'toolChange' in event and event['toolChange']['position'] is not None:
                next_motion=next(e['motion'] for e in after[index+1:] if 'motion' in e)
                self.assertEqual(replay['motions'][next_motion]['tool'],event['toolChange']['tool'])


class OrderedAdmission(unittest.TestCase):
    def test_policy_has_its_own_positive_gap_and_no_implicit_original_plane_waiver(self):
        from schemaxis.adaptors.freecad.cam_pointed import clearance
        from schemaxis.core.faults import SchemaxisError
        self.assertEqual(clearance({'kind':'evolvingStock','minimumSeparation':.5}),
                         {'kind':'evolvingStock','minimumSeparation':.5})
        self.assertEqual(clearance({'kind':'aboveBlank','axialClearance':1}),
                         {'kind':'aboveBlank','axialClearance':1})
        for raw in ({'kind':'evolvingStock','minimumSeparation':0},
                    {'kind':'evolvingStock','minimumSeparation':True},
                    {'kind':'evolvingStock','minimumSeparation':1,'axialClearance':1},
                    {'kind':'aboveBlank','minimumSeparation':1}):
            with self.subTest(raw=raw),self.assertRaises(SchemaxisError):clearance(raw)

    def test_missing_tool_transition_or_motion_never_reaches_geometry(self):
        import copy
        from schemaxis.adaptors.freecad.cam_ordered import preflight_ordered
        from schemaxis.core.faults import SchemaxisError
        replay=parse(program(),tools(),3,ordered=True)
        p={'tools':tools(),'stockBounds':[-20,20,-15,15,-14,0],
           'setup':{'toolClearance':{'kind':'evolvingStock','minimumSeparation':.5}}}
        preflight_ordered(p,replay)
        for drop in (0,1,2,len(replay['events'])-1):
            altered=copy.deepcopy(replay);altered['events'].pop(drop)
            with self.subTest(drop=drop),self.assertRaises(SchemaxisError):preflight_ordered(p,altered)


class RapidMaskReuse(unittest.TestCase):
    def test_only_same_tool_exact_xy_and_previous_vertical_feed_enclosure(self):
        from schemaxis.adaptors.freecad.cam_ordered import reusable_vertical_rapid as reuse
        feed={'code':1,'tool':'pilot','from':[1.,2.,3.],'to':[1.,2.,-10.]}
        rapid={'code':0,'tool':'pilot','from':[1.,2.,-10.],'to':[1.,2.,5.]}
        self.assertTrue(reuse(rapid,feed,0.)) #upper extension wholly above original
        self.assertTrue(reuse(dict(rapid,**{'to':[1.,2.,-4.]}),feed,0.))
        self.assertFalse(reuse(dict(rapid,**{'from':[1.,2.,-10.000001]}),feed,0.))
        self.assertFalse(reuse(dict(rapid,tool='other'),feed,0.))
        self.assertFalse(reuse(dict(rapid,**{'from':[1.000001,2.,-10.]}),feed,0.))
        self.assertFalse(reuse(dict(rapid,code=1),feed,0.))
        self.assertFalse(reuse(rapid,None,0.))
        deep=dict(feed,**{'from':[1.,2.,-3.]})
        self.assertFalse(reuse(rapid,deep,0.)) #unproved upper extension IN stock
        self.assertTrue(reuse(dict(rapid,**{'to':[1.,2.,-4.]}),deep,0.))

    def test_cache_domain_is_only_a_connected_union_of_actual_feed_tip_intervals(self):
        from schemaxis.adaptors.freecad.cam_ordered import cleared_column,reusable_vertical_rapid
        first={'code':1,'tool':'pilot','from':[1.,2.,3.],'to':[1.,2.,-2.]}
        # A later short peck does NOT alone cover the upper retraction path.
        peck={'code':1,'tool':'pilot','from':[1.,2.,-1.746],'to':[1.,2.,-2.193]}
        up={'code':0,'tool':'pilot','from':[1.,2.,-2.193],'to':[1.,2.,3.]}
        self.assertFalse(reusable_vertical_rapid(up,peck,0.))
        domain,action=cleared_column(peck,first)
        self.assertEqual(action,'merge');self.assertTrue(reusable_vertical_rapid(up,domain,0.))
        self.assertEqual(domain['from'],[1.,2.,3.]);self.assertEqual(domain['to'],[1.,2.,-2.193])
        self.assertEqual(cleared_column(peck,domain),(domain,'keep'))
        gap=dict(peck,**{'from':[1.,2.,-3.],'to':[1.,2.,-4.]})
        self.assertEqual(cleared_column(gap,domain),(gap,'replace'))
        other=dict(peck,tool='other')
        self.assertEqual(cleared_column(other,domain),(other,'replace'))
