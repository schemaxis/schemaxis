"""Physical depth and declared-envelope controls before public registration."""
import copy
import math
import unittest

from schemaxis.adaptors.freecad import cam_pointed as pointed
from schemaxis.core.faults import SchemaxisError


def raw_tool(**changes):
    return {'id': 'pilot', 'kind': 'drill', 'diameter': 4, 'tipAngle': 90,
            'cuttingReach': 10, 'length': 35, 'rpm': 5000, 'feed': 400,
            'plunge': 100, **changes}


def setup():
    return {'safe': 3, 'clearance': 5,
            'toolClearance': {'kind': 'aboveBlank', 'axialClearance': 1}}


class PointedIntent(unittest.TestCase):
    def tool(self, **changes):
        return pointed.tool(raw_tool(**changes), 0, '$.tools[0]')

    def op(self, **changes):
        raw = {'id': 'hole', 'operation': 'drill', 'tool': 'pilot',
               'locations': {'kind': 'explicit', 'centres': [[0, 0]]},
               'bottom': 14, 'depthReference': 'fullDiameter', **changes}
        return pointed.operation(raw, self.tool(), [-20, 20, -15, 15, 0, 20],
                                 [0, 0, 22], setup(), '$.operations[0]')

    def test_tip_and_full_diameter_equal_numbers_are_different_physical_cuts(self):
        tip = self.op(depthReference='tip')
        full = self.op()
        self.assertAlmostEqual(tip['finish'], -8)
        self.assertAlmostEqual(full['finish'], -10)
        self.assertEqual(tip['nativeFinish'], full['nativeFinish'])
        self.assertEqual((tip['extraOffset'], full['extraOffset']), ('None', 'Drill Tip'))
        self.assertEqual(full['junction'], -8)
        self.assertNotEqual(tip['cycle'], {})
        self.assertEqual(full['sourceRegime']['kind'], 'blind')

    def test_source_regimes_do_not_invent_missing_cones_or_cylinders(self):
        through = self.op(bottom=0, throughClearance=3)
        self.assertEqual(through['sourceRegime'], {'frame': 'source', 'kind': 'through', 'cone': None, 'cylinder': [0, 20]})
        clipped = self.op(bottom=-1, depthReference='tip', throughClearance=2)
        self.assertEqual(clipped['sourceRegime']['kind'], 'clippedCone')
        self.assertEqual(clipped['sourceRegime']['cone'][0], 0)
        spot = self.op(bottom=19.5, depthReference='tip',
                       locations={'kind': 'explicit', 'centres': [[19, 0]]})
        self.assertEqual(spot['sourceRegime']['kind'], 'spot')
        self.assertIsNone(spot['sourceRegime']['cylinder'])
        self.assertEqual(spot['sourceRegime']['cone'][1], 20)
        for changes in ({'bottom': 0}, {'bottom': -1, 'depthReference': 'tip'},
                        {'bottom': 0, 'throughClearance': .5},
                        {'bottom': 20, 'depthReference': 'tip'}, {'depthReference': 'FinalDepth'}):
            with self.subTest(changes=changes), self.assertRaises(SchemaxisError):
                self.op(**changes)

    def test_tip_clearance_includes_posted_word_rounding_and_actual_cycles(self):
        tool = self.tool()
        spec = {'id': 'hole', 'operation': 'drill', 'tool': 'pilot',
                'centres': [[0, 0]], 'finish': -22, 'throughClearance': 2}
        p = {'tools': [tool], 'stockBounds': [-20, 20, -15, 15, -20, 0],
             'operations': [spec]}
        # Nominal equality has no positive room for the prospective word error.
        with self.assertRaises(SchemaxisError):
            pointed.admit_tip_clearance(p)
        spec['throughClearance'] = 2.000001
        self.assertTrue(pointed.admit_tip_clearance(p))
        self.assertTrue(pointed.admit_tip_clearance(p, {'cycles': [{'bottom': -22}]}))
        with self.assertRaises(SchemaxisError):
            pointed.admit_tip_clearance(p, {'cycles': [{'bottom': -22.000002}]} )
        with self.assertRaises(SchemaxisError):
            pointed.admit_tip_clearance(p, {'cycles': []})
        spec.pop('throughClearance');spec['finish'] = -20
        with self.assertRaises(SchemaxisError):
            pointed.admit_tip_clearance(p)
        spec['finish'] = -19.999999
        self.assertTrue(pointed.admit_tip_clearance(p))

    def test_new_tool_declares_reach_separately_from_native_length(self):
        raw = raw_tool()
        original = copy.deepcopy(raw)
        compiled = pointed.tool(raw, 0, '$.tools[0]')
        self.assertEqual(raw, original)
        self.assertEqual(compiled, pointed.tool(raw, 0, '$.tools[0]'))
        self.assertAlmostEqual(compiled['tipHeight'], 2)
        self.assertNotIn('cuttingLength', compiled)
        self.assertNotIn('shankDiameter', compiled)
        for changes in ({'tipAngle': 0}, {'tipAngle': 180}, {'tipAngle': True},
                        {'cuttingReach': 1}, {'cuttingReach': 35},
                        {'kind': 'Endmill'}, {'flutes': 2.5}, {'nativeTool': 'foreign'}):
            with self.subTest(changes=changes), self.assertRaises(SchemaxisError):
                self.tool(**changes)
        fractional = self.tool(diameter=3.175, tipAngle=118)
        self.assertAlmostEqual(fractional['tipHeight'], .9538662327062519)

    def test_missing_clearance_and_raw_native_controls_are_refused(self):
        for policy in ({}, {'kind': 'afterFace', 'axialClearance': 1},
                       {'kind': 'aboveBlank', 'axialClearance': 0},
                       {'kind': 'aboveBlank', 'axialClearance': True},
                       {'kind': 'aboveBlank', 'axialClearance': 1, 'ignoreStock': True}):
            with self.subTest(policy=policy), self.assertRaises(SchemaxisError):
                pointed.clearance(policy)
        with self.assertRaises(SchemaxisError):
            pointed.operation({'depthReference': 'tip'}, self.tool(),
                              [-20, 20, -15, 15, 0, 20], [0, 0, 22],
                              {'safe': 3, 'clearance': 5}, '$.operations[0]')


class PhysicalEnvelope(unittest.TestCase):
    def test_shallow_wide_shank_is_opt_in_and_never_changes_old_default(self):
        from schemaxis.adaptors.freecad import cam_tools
        raw = {'id': 'shallow', 'kind': 'flatEndmill', 'diameter': 3.175,
               'cuttingLength': 5, 'length': 35, 'shankDiameter': 6,
               'rpm': 5000, 'feed': 400, 'plunge': 100}
        with self.assertRaises(SchemaxisError):
            cam_tools.named([raw], 22)
        t = pointed.flat_tool(raw, 0, setup(), 't')
        self.assertEqual((t['cuttingLength'], t['shankDiameter']), (5, 6))
        self.assertAlmostEqual(t['noncuttingStart'], 4.99)
        p = {'setup': setup(), 'stockBounds': [-20, 20, -15, 15, -22, 0],
             'tools': [t], 'operations': [{'tool': 'shallow', 'finish': -2}]}
        self.assertTrue(pointed.admit_reach(p))
        p['operations'][0]['finish'] = -5
        with self.assertRaises(SchemaxisError):
            pointed.admit_reach(p)
        p['operations'][0]['finish'] = -3.995
        self.assertGreater(-3.995+t['cuttingLength'], 1)
        # Fixed native template overlap puts actual wider non-cutting material
        # below c: using c alone incorrectly passes this positive-gap boundary.
        with self.assertRaises(SchemaxisError):
            pointed.admit_reach(p)
        with self.assertRaises(SchemaxisError):
            pointed.flat_tool(raw, 0, {'safe': 3}, 't')

    def test_holder_contains_positive_insertion_and_has_no_gap_or_missing_bit(self):
        t = pointed.tool(raw_tool(holder={'stickOut': 20, 'steps': [
            {'diameter': 12, 'length': 10}, {'diameter': 20, 'length': 8}]}), 0, 't')
        self.assertEqual(t['holder']['steps'], [{'start': 20, 'end': 30, 'radius': 6},
                                               {'start': 30, 'end': 38, 'radius': 10}])
        self.assertEqual(pointed.noncutting_start(t), 10)
        for holder in ({'stickOut': 9, 'steps': [{'diameter': 12, 'length': 30}]},
                       {'stickOut': 35, 'steps': [{'diameter': 12, 'length': 5}]},
                       {'stickOut': 20, 'steps': [{'diameter': 3, 'length': 20}]},
                       {'stickOut': 20, 'steps': [{'diameter': 12, 'length': 5}]},
                       {'stickOut': 20, 'steps': [{'diameter': 12, 'length': 20, 'start': 21}]}):
            with self.subTest(holder=holder), self.assertRaises(SchemaxisError):
                pointed.tool(raw_tool(holder=holder), 0, 't')

    def plan(self, finish=-8):
        return {'setup': setup(), 'stockBounds': [-20, 20, -15, 15, -22, 0],
                'tools': [pointed.tool(raw_tool(), 0, 't')],
                'operations': [{'tool': 'pilot', 'finish': finish}]}

    def test_short_tool_can_clear_shallow_cut_but_not_post_face_plane(self):
        p = self.plan()
        proof = pointed.admit_reach(p)
        self.assertGreater(proof['checked'][0]['minimumNoncuttingZ'], 1)
        self.assertEqual(proof['originalBlankTop'], 0)
        # Source top after facing is -2. A wrong post-face test would accept
        # minimum noncutting Z=0, but the original blank+positive gap refuses.
        with self.assertRaises(SchemaxisError):
            pointed.admit_reach(self.plan(-10))
        # Equality at the engineering gap is conservatively refused when its
        # posted-word rounding interval can cross that gap.
        with self.assertRaises(SchemaxisError):
            pointed.admit_reach(self.plan(-9))
        self.assertTrue(pointed.admit_reach(self.plan(-9+1e-6)))

    def test_whole_noncutting_bit_and_all_rapid_motions_are_checked(self):
        p = self.plan()
        p['tools'][0]['holder'] = {'stickOut': 20, 'steps': [{'start': 20, 'end': 38, 'radius': 6}]}
        replay = {'motions': [{'tool': 'pilot', 'code': 1, 'from': [0, 0, 5], 'to': [0, 0, -8]},
                              {'tool': 'pilot', 'code': 0, 'from': [0, 0, -8], 'to': [0, 0, -11]}]}
        with self.assertRaises(SchemaxisError):
            pointed.admit_reach(p, replay)
        # Testing only the holder start would incorrectly admit this motion.
        self.assertGreater(-11+20, p['setup']['toolClearance']['axialClearance'])
        replay['motions'].pop()
        self.assertTrue(pointed.admit_reach(p, replay))

    def test_fresh_physical_geometry_can_only_make_envelope_more_conservative(self):
        p = self.plan(-8)
        with self.assertRaises(SchemaxisError):
            pointed.admit_reach(p, actual_starts={'pilot': 8.5})
        with self.assertRaises(SchemaxisError):
            pointed.admit_reach(p, actual_starts={})
        p['operations'][0]['finish'] = -10
        with self.assertRaises(SchemaxisError):
            pointed.admit_reach(p, actual_starts={'pilot': 20})


class AggregateBudgets(unittest.TestCase):
    def test_all_costs_precede_allocation_and_semantic_counts_are_exact(self):
        from schemaxis.adaptors.freecad.cam_mixed_budget import preflight, LIMITS
        self.assertEqual(preflight(**LIMITS), LIMITS)
        for key in LIMITS:
            for value in (LIMITS[key]+1, -1, True, 1.0):
                with self.subTest(key=key, value=value), self.assertRaises(SchemaxisError):
                    preflight(**dict(LIMITS, **{key: value}))
        with self.assertRaises(SchemaxisError):
            preflight(pieces=1)

    def test_actual_boolean_work_and_result_growth_stay_bounded(self):
        from schemaxis.adaptors.freecad.cam_mixed_budget import BooleanBudget
        budget = BooleanBudget()
        budget.before(1000, 1000)
        budget.before(1000, 1000)
        self.assertEqual((budget.operations, budget.face_pairs), (2, 2000000))
        with self.assertRaises(SchemaxisError):
            budget.before(1, 1)
        self.assertEqual((budget.operations, budget.face_pairs), (2, 2000000))
        with self.assertRaises(SchemaxisError):
            budget.after(8193, 20)
        with self.assertRaises(SchemaxisError):
            budget.after(10, 16385)


class SeparateCompiledPlan(unittest.TestCase):
    def document(self):
        from test_freecad_cam import document
        d = document()
        d.pop('tool')
        d['stock'] = {'top': 0}
        d['tools'] = [raw_tool()]
        d['setup'] = setup()
        d['operations'] = [{'id': 'pilot', 'operation': 'drill', 'tool': 'pilot',
                            'locations': {'kind': 'explicit', 'centres': [[0, 0]]},
                            'bottom': 6, 'depthReference': 'fullDiameter'}]
        return d

    def test_explicit_policy_selects_the_separate_compiled_family(self):
        from schemaxis.adaptors.freecad.cam_plan3 import plan
        from schemaxis.adaptors.freecad import cam
        d = self.document()
        original = copy.deepcopy(d)
        p = plan(d)
        self.assertEqual(d, original)
        self.assertEqual(p['version'], 'schemaxis.freecad.cam.plan/3')
        self.assertAlmostEqual(p['operations'][0]['finish'], -6)
        self.assertEqual(p['operations'][0]['nativeFinish'], -4)
        self.assertEqual(cam.plan(d),p)

    def test_full_recipe_binds_tool_usage_kind_and_original_blank_reach(self):
        from schemaxis.adaptors.freecad.cam_plan3 import plan
        d = self.document()
        for mutate in (lambda x: x['operations'][0].update(tool='missing'),
                       lambda x: x['operations'][0].update(operation='pocket', floor=[0, 0, 6]),
                       lambda x: x['setup'].pop('toolClearance'),
                       lambda x: x['tools'].append(dict(x['tools'][0], id='unused')),
                       lambda x: x.update(stock={'top': 2}),
                       lambda x: x['operations'][0].update(bottom=0, throughClearance=3)):
            value = copy.deepcopy(d)
            mutate(value)
            with self.subTest(document=value), self.assertRaises(SchemaxisError):
                plan(value)


if __name__ == '__main__':
    unittest.main()
