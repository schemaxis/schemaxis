"""Host tests of the device clock model. Skews, medians, drift rates and cycle residuals are hand-computed literals (seconds); the model is
checked against its own stated definition (skew = recorded - true) and never against ExifTool."""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))

from schemaxis.adaptors.exiftool import clockmodel as cm, timecalc as tc  # noqa: E402


def dev(make, model='M', serial=None, **states):
    d = {'cameraMake': {'state': 'present', 'value': make}, 'cameraModel': {'state': 'present', 'value': model},
         'bodySerialNumber': {'state': 'present', 'value': serial} if serial else {'state': 'absent'}}
    d.update(states)
    return d


def item(item_id, local, offset='+01:00', device=None, gps=None, **flags):
    return {'id': item_id, 'wall': tc.parse_local(local)[0], 'offset': None if offset is None else tc.parse_offset(offset), 'gpsUtc': None if gps is None else tc.parse_local(gps)[0],
            'device': device or dev('A', serial='1'), 'timeConflict': flags.get('timeConflict', False), 'subSecondConflict': flags.get('subSecondConflict', False)}


def ref(item_id, true_local, offset='+01:00', **extra):
    return {'item': item_id, 'trueLocal': true_local, 'trueOffset': offset, **extra}


def by_id(report):
    return {i['id']: i for i in report['items']}


def group(report, gid):
    return next(g for g in report['groups'] if g['id'] == gid)


def problem(call, *args):
    try:
        call(*args)
    except cm.ClockProblem as error:
        return error.code, error.location
    return None


class Grouping(unittest.TestCase):
    def test_recorded_device_groups_in_manifest_order_with_states(self):
        items = [item('a1', '2026-03-01T12:00:00'), item('b1', '2026-03-01T12:00:00', device=dev('B', 'N')), item('a2', '2026-03-01T12:00:01'),
                 item('c1', '2026-03-01T12:00:02', device=dev('A', serial=None))]
        report = cm.reconcile(items, {})
        self.assertEqual([(g['id'], g['members']) for g in report['groups']], [('dev1', ['a1', 'a2']), ('dev2', ['b1']), ('dev3', ['c1'])])
        self.assertFalse(group(report, 'dev1')['mayMergeBodies'])
        self.assertTrue(group(report, 'dev3')['mayMergeBodies'])             # serial absent: two bodies of one model are indistinguishable
        self.assertEqual(group(report, 'dev3')['key'][2], ['bodySerialNumber', 'absent', None])    # never merged into the group that has the value

    def test_ambiguous_identity_is_ungroupable_not_guessed(self):
        items = [item('a1', '2026-03-01T12:00:00'), item('x1', '2026-03-01T12:00:00', device=dev('A', serial='1', cameraMake={'state': 'ambiguous'}))]
        report = cm.reconcile(items, {})
        self.assertEqual(report['ungroupable'], ['x1'])
        row = by_id(report)['x1']
        self.assertEqual((row['group'], row['groupState']), (None, 'ungroupable'))
        self.assertIn('DEVICE_IDENTITY_UNRESOLVED', row['findings'])
        fixed = cm.reconcile(items, {'groups': {'by': 'recordedDevice', 'itemOverrides': [{'item': 'x1', 'group': 'dev1'}]}})
        self.assertEqual(fixed['ungroupable'], [])
        self.assertEqual(group(fixed, 'dev1')['members'], ['a1', 'x1'])

    def test_declared_groups_must_cover_every_item_exactly_once(self):
        items = [item('a1', '2026-03-01T12:00:00'), item('p1', '2026-03-01T12:00:00')]
        ok = cm.reconcile(items, {'groups': {'by': 'declared', 'members': [{'group': 'nikon', 'items': ['a1']}, {'group': 'phone', 'items': ['p1']}]}})
        self.assertEqual([g['id'] for g in ok['groups']], ['nikon', 'phone'])
        self.assertEqual([f['code'] for f in ok['findings']], [])
        mixed = cm.reconcile([item('a1', '2026-03-01T12:00:00'), item('b1', '2026-03-01T12:00:00', device=dev('B'))],
                             {'groups': {'by': 'declared', 'members': [{'group': 'all', 'items': ['a1', 'b1']}]}})
        self.assertEqual(mixed['findings'], [{'code': 'declaredGroupMixesRecordedDevices', 'group': 'all', 'devices': 2}])       # information, not a fault
        for members in ([{'group': 'g', 'items': ['a1']}], [{'group': 'g', 'items': ['a1', 'p1', 'zz']}], [{'group': 'g', 'items': ['a1', 'p1']}, {'group': 'h', 'items': ['p1']}],
                        [{'group': '1bad', 'items': ['a1', 'p1']}], [{'group': 'g', 'items': ['a1', 'p1']}, {'group': 'g', 'items': []}]):
            self.assertEqual(problem(cm.reconcile, items, {'groups': {'by': 'declared', 'members': members}})[0], 'GROUP_MEMBERSHIP_INVALID', members)
        self.assertEqual(problem(cm.reconcile, items, {'groups': {'by': 'recordedDevice', 'itemOverrides': [{'item': 'nope', 'group': 'g'}]}})[0], 'UNKNOWN_ITEM')


class Constant(unittest.TestCase):
    def test_T7_median_and_residuals(self):
        # skew = recorded - true: -5, -4, -6 seconds -> median -5, residuals 0, +1, -1, spread 2 <= tolerance 2 -> anchored
        items = [item('a1', '2026-03-01T12:00:00'), item('a2', '2026-03-01T13:00:01'), item('a3', '2026-03-01T14:00:00')]
        refs = [ref('a1', '2026-03-01T12:00:05'), ref('a2', '2026-03-01T13:00:05'), ref('a3', '2026-03-01T14:00:06')]
        report = cm.reconcile(items, {'references': refs})
        g = group(report, 'dev1')
        self.assertEqual((g['state'], g['skewSeconds'], g['spreadSeconds'], g['anchoredBy']), ('anchored', '-5', '2', 'references'))
        self.assertEqual({r['item']: r['residualSeconds'] for r in g['residuals']}, {'a1': '0', 'a2': '1', 'a3': '-1'})
        row = by_id(report)['a1']
        self.assertEqual((row['proposedLocal'], row['proposedOffset'], row['proposedInstant']), ('2026-03-01T12:00:05', '+01:00', '2026-03-01T11:00:05'))
        self.assertEqual({r['item']: r['declared'] for r in report['references']}, {'a1': True, 'a2': True, 'a3': True})

    def test_T1_reference_skew_with_subsecond(self):
        items = [item('a1', '2026-03-01T12:00:00.12')]
        report = cm.reconcile(items, {'references': [ref('a1', '2026-03-01T12:05:30.5')]})
        self.assertEqual(report['references'][0]['instantSkewSeconds'], '-330.38')
        self.assertEqual(report['references'][0]['wallSkewSeconds'], '-330.38')
        self.assertEqual(by_id(report)['a1']['proposedLocal'], '2026-03-01T12:05:30.5')

    def test_T8_conflict_is_listed_not_averaged(self):
        items = [item('a1', '2026-03-01T12:00:00'), item('a2', '2026-03-01T13:00:25')]
        report = cm.reconcile(items, {'references': [ref('a1', '2026-03-01T12:00:05'), ref('a2', '2026-03-01T13:00:00')]})
        g = group(report, 'dev1')
        self.assertEqual((g['state'], g['spreadSeconds']), ('conflicting', '30'))
        self.assertEqual({r['item']: r['residualSeconds'] for r in g['residuals']}, {'a1': '-15', 'a2': '15'})
        row = by_id(report)['a1']
        self.assertEqual((row['groupState'], row['proposedLocal'], row['skewSeconds']), ('conflicting', None, None))        # nothing is correctable

    def test_offset_error_is_a_finding_and_identity_holds(self):
        # camera recorded 12:00:00 at +00:00 for a moment whose true label is 12:00:00 at +01:00 (an hour later in UTC terms? no: wall equal, label differs)
        items = [item('a1', '2026-03-01T12:00:00', offset='+00:00')]
        report = cm.reconcile(items, {'references': [ref('a1', '2026-03-01T12:00:00', '+01:00')]})
        r = report['references'][0]
        self.assertEqual((r['wallSkewSeconds'], r['offsetErrorSeconds'], r['instantSkewSeconds']), ('0', '-3600', '3600'))      # instant = wall - offsetError
        self.assertIn('offsetErrorDetected', by_id(report)['a1']['findings'])

    def test_gps_stamp_disagreement_is_independent_evidence(self):
        items = [item('a1', '2026-03-01T12:00:00', gps='2026-03-01T11:00:05'), item('a2', '2026-03-01T13:00:00', gps='2026-03-01T12:00:00')]
        report = cm.reconcile(items, {'references': [ref('a1', '2026-03-01T12:00:05')], 'gpsToleranceSeconds': 120})
        rows = by_id(report)
        self.assertNotIn('gpsStampDisagrees', rows['a1']['findings'])          # proposed true instant 11:00:05Z equals the stamp
        self.assertNotIn('gpsStampDisagrees', rows['a2']['findings'])          # skew -5 -> true instant 12:00:05Z vs stamp 12:00:00Z: 5 s <= 120 s
        report = cm.reconcile(items, {'references': [ref('a1', '2026-03-01T12:00:05')], 'gpsToleranceSeconds': 2})
        self.assertIn('gpsStampDisagrees', by_id(report)['a2']['findings'])
        self.assertEqual(group(report, 'dev1')['skewSeconds'], '-5')           # the stamp never fed the estimate


class Offsets(unittest.TestCase):
    def test_T11_missing_offset_assumed_offset_and_wall_only(self):
        items = [item('a1', '2026-03-01T12:00:00', offset=None), item('b1', '2026-03-01T12:00:20', offset=None, device=dev('B'))]
        spec = {'simultaneous': [{'items': ['a1', 'b1']}]}
        report = cm.reconcile(items, spec)
        self.assertEqual(report['edges'][0]['code'], 'OFFSET_UNKNOWN')
        self.assertIn('OFFSET_UNKNOWN', by_id(report)['a1']['findings'])
        self.assertEqual(by_id(report)['a1']['basis'], 'wallOnly')
        # a reference on a wall-only item gives a wall skew only, and the group is anchored on wall readings
        wall = cm.reconcile(items, {'references': [ref('a1', '2026-03-01T12:00:07', '+01:00')]})
        self.assertEqual((wall['references'][0]['wallSkewSeconds'], wall['references'][0]['instantSkewSeconds']), ('-7', None))
        self.assertEqual(by_id(wall)['a1']['proposedLocal'], '2026-03-01T12:00:07')
        assumed = cm.reconcile(items, {**spec, 'assumedOffsets': [{'group': 'dev1', 'offset': '+01:00'}, {'group': 'dev2', 'offset': '+01:00'}]})
        self.assertEqual(by_id(assumed)['a1']['basis'], 'assumedOffset')
        self.assertEqual(assumed['edges'][0]['state'], 'edge')
        self.assertEqual(assumed['edges'][0]['differenceSeconds'], '20')

    def test_recorded_offset_wins_over_assumption_and_is_reported(self):
        items = [item('a1', '2026-03-01T12:00:00', offset='+02:00')]
        report = cm.reconcile(items, {'assumedOffsets': [{'group': 'dev1', 'offset': '+01:00'}]})
        row = by_id(report)['a1']
        self.assertEqual(row['basis'], 'recordedOffset')
        self.assertIn('assumedOffsetDiffers', row['findings'])


class AcrossGroups(unittest.TestCase):
    def test_T6_two_devices_one_reference_one_simultaneity(self):
        # A is 5 s behind (skew -5). a5 and b3 are the same moment: b3 reads 30 s more than a5, so B is 25 s ahead (skew +25)
        items = [item('a1', '2026-03-01T12:00:00'), item('a5', '2026-03-01T12:10:00'), item('b3', '2026-03-01T12:10:30', device=dev('B', 'N')), item('b9', '2026-03-01T15:00:25', device=dev('B', 'N'))]
        report = cm.reconcile(items, {'references': [ref('a1', '2026-03-01T12:00:05')], 'simultaneous': [{'items': ['a5', 'b3']}]})
        self.assertEqual((group(report, 'dev1')['state'], group(report, 'dev1')['skewSeconds']), ('anchored', '-5'))
        self.assertEqual((group(report, 'dev2')['state'], group(report, 'dev2')['skewSeconds'], group(report, 'dev2')['anchoredBy']), ('anchored', '25', 'path'))
        rows = by_id(report)
        self.assertEqual((rows['b3']['proposedLocal'], rows['b9']['proposedLocal'], rows['a5']['proposedLocal']), ('2026-03-01T12:10:05', '2026-03-01T15:00:00', '2026-03-01T12:10:05'))

    def test_unanchored_component_reports_relative_skew_only(self):
        items = [item('a5', '2026-03-01T12:10:00'), item('b3', '2026-03-01T12:10:30', device=dev('B', 'N'))]
        report = cm.reconcile(items, {'simultaneous': [{'items': ['a5', 'b3']}]})
        self.assertEqual([g['state'] for g in report['groups']], ['unanchored', 'unanchored'])
        self.assertEqual(by_id(report)['b3']['proposedLocal'], None)

    def test_no_reference_and_no_edge_is_insufficient(self):
        report = cm.reconcile([item('a1', '2026-03-01T12:00:00')], {})
        self.assertEqual(group(report, 'dev1')['state'], 'insufficient')

    def test_assume_correct_anchors_a_group_as_declared(self):
        items = [item('a5', '2026-03-01T12:10:00'), item('p1', '2026-03-01T12:10:30', device=dev('P', 'Phone'))]
        report = cm.reconcile(items, {'assumeCorrect': ['dev2'], 'simultaneous': [{'items': ['a5', 'p1']}]})
        self.assertEqual((group(report, 'dev2')['skewSeconds'], group(report, 'dev1')['skewSeconds']), ('0', '-30'))
        self.assertEqual(report['declared']['assumeCorrect'], ['dev2'])
        self.assertEqual(by_id(report)['a5']['proposedLocal'], '2026-03-01T12:10:30')

    def test_T10_cycle_conflict_publishes_the_residual(self):
        # A-B reads +10 s, B-C +10 s, C-A reads -13 s (a4 is 7 s after a1): the loop sums to 7 s with tolerance 1 -> the whole component conflicts
        items = [item('a1', '2026-03-01T12:00:00'), item('a4', '2026-03-01T12:00:07'), item('b1', '2026-03-01T12:00:10', device=dev('B', 'N')), item('c1', '2026-03-01T12:00:20', device=dev('C', 'O'))]
        spec = {'assumeCorrect': ['dev1'], 'simultaneous': [{'items': ['a1', 'b1'], 'toleranceSeconds': '1'}, {'items': ['b1', 'c1'], 'toleranceSeconds': '1'},
                                                              {'items': ['c1', 'a4'], 'toleranceSeconds': '1'}]}
        report = cm.reconcile(items, spec)
        cycle = next(c for c in report['cycles'] if 'residualSeconds' in c)
        self.assertEqual((cycle['residualSeconds'], cycle['toleranceSeconds'], cycle['state']), ('7', '1', 'conflicting'))
        self.assertTrue(all(g['state'] == 'conflicting' for g in report['groups']))
        self.assertTrue(all(i['proposedLocal'] is None for i in report['items']))
        # the same loop within a tolerance of 7 s is accepted
        loose = cm.reconcile(items, {**spec, 'simultaneous': [dict(a, toleranceSeconds='7') for a in spec['simultaneous']], 'toleranceSeconds': '7'})
        self.assertEqual([c['state'] for c in loose['cycles'] if 'residualSeconds' in c], ['consistent'])

    def test_consistent_cycle_stays_anchored(self):
        items = [item('a1', '2026-03-01T12:00:00'), item('a2', '2026-03-01T12:00:10', device=dev('B', 'N')), item('a3', '2026-03-01T12:00:20', device=dev('C', 'O'))]
        spec = {'assumeCorrect': ['dev1'], 'simultaneous': [{'items': ['a1', 'a2']}, {'items': ['a2', 'a3']}, {'items': ['a3', 'a1']}]}
        report = cm.reconcile(items, spec)
        self.assertEqual([c['state'] for c in report['cycles']], ['consistent'])
        self.assertEqual({g['id']: g['skewSeconds'] for g in report['groups']}, {'dev1': '0', 'dev2': '10', 'dev3': '20'})

    def test_same_group_assertion_checks_consistency_only(self):
        items = [item('a1', '2026-03-01T12:00:00'), item('a2', '2026-03-01T12:00:05')]
        report = cm.reconcile(items, {'simultaneous': [{'items': ['a1', 'a2'], 'toleranceSeconds': '1'}]})
        self.assertEqual(report['edges'][0]['state'], 'conflicting')
        self.assertEqual(group(report, 'dev1')['state'], 'conflicting')
        ok = cm.reconcile(items, {'simultaneous': [{'items': ['a1', 'a2'], 'toleranceSeconds': '5'}]})
        self.assertEqual(ok['edges'][0]['state'], 'consistent')


class Drift(unittest.TestCase):
    def test_T9_linear_drift_exact(self):
        # skews 0 at t0 and 8.64 s one day later -> rate 1e-4 s/s; at mid-span the skew is 4.32 s; an item 10 s past the span is outside it
        # the fit runs on recorded instants: r1 is recorded exactly 86400 s after r0 and its true time is 8.64 s earlier than recorded
        items = [item('r0', '2026-03-01T00:00:00'), item('mid', '2026-03-01T12:00:00'), item('r1', '2026-03-02T00:00:00'), item('late', '2026-03-02T00:00:10')]
        refs = [ref('r0', '2026-03-01T00:00:00'), ref('r1', '2026-03-01T23:59:51.36')]
        report = cm.reconcile(items, {'references': refs, 'model': 'linearDrift'})
        g = group(report, 'dev1')
        self.assertEqual((g['state'], g['model'], g['drift']['ratePerSecond'], g['drift']['rateSecondsPerDay']), ('anchored', 'linearDrift', '0.0001', '8.64'))
        rows = by_id(report)
        self.assertEqual((rows['mid']['skewSeconds'], rows['mid']['proposedLocal']), ('4.32', '2026-03-01T11:59:55.68'))
        self.assertEqual((rows['late']['groupState'], rows['late']['proposedLocal']), ('outsideReferenceSpan', None))
        self.assertIn('outsideReferenceSpan', rows['late']['findings'])
        allowed = cm.reconcile(items, {'references': refs, 'model': 'linearDrift', 'maxDriftExtrapolationSeconds': 20})
        self.assertEqual((by_id(allowed)['late']['skewSeconds'], by_id(allowed)['late']['proposedLocal']), ('8.641', '2026-03-02T00:00:01.359'))

    def test_drift_needs_two_references_apart_and_a_plausible_rate(self):
        one = cm.reconcile([item('r0', '2026-03-01T00:00:00')], {'references': [ref('r0', '2026-03-01T00:00:00')], 'model': 'linearDrift'})
        self.assertEqual(group(one, 'dev1')['state'], 'insufficient')
        close = cm.reconcile([item('r0', '2026-03-01T00:00:00'), item('r1', '2026-03-01T00:00:30')], {'references': [ref('r0', '2026-03-01T00:00:00'), ref('r1', '2026-03-01T00:00:30')], 'model': 'linearDrift'})
        self.assertEqual(group(close, 'dev1')['state'], 'insufficient')
        # 1000 s of skew change in 1000 s is a rate of 1: implausible against the 0.001 default
        fast = cm.reconcile([item('r0', '2026-03-01T00:00:00'), item('r1', '2026-03-01T00:33:20')], {'references': [ref('r0', '2026-03-01T00:00:00'), ref('r1', '2026-03-01T00:00:00')], 'model': 'linearDrift'})
        self.assertEqual(group(fast, 'dev1')['state'], 'conflicting')

    def test_drift_three_points_least_squares(self):
        # skews 0, 1, 5 at recorded times 0, 100, 200 s: slope = (500 / 20000) = 0.025, mean skew 2, intercept = 2 - 0.025*100 = -0.5; residuals 0.5, -1, 0.5
        items = [item('r0', '2026-03-01T00:00:00'), item('r1', '2026-03-01T00:01:40'), item('r2', '2026-03-01T00:03:20')]
        refs = [ref('r0', '2026-03-01T00:00:00'), ref('r1', '2026-03-01T00:01:39'), ref('r2', '2026-03-01T00:03:15')]
        report = cm.reconcile(items, {'references': refs, 'model': 'linearDrift', 'toleranceSeconds': '3', 'maxDriftRate': '0.05'})
        g = group(report, 'dev1')
        self.assertEqual((g['drift']['ratePerSecond'], g['drift']['interceptSeconds']), ('0.025', '-0.5'))
        self.assertEqual({r['item']: r['residualSeconds'] for r in g['residuals']}, {'r0': '0.5', 'r1': '-1', 'r2': '0.5'})


class Plan(unittest.TestCase):
    def test_reference_faults_have_exact_locations(self):
        items = [item('a1', '2026-03-01T12:00:00')]
        cases = [([ref('zz', '2026-03-01T12:00:00')], 'UNKNOWN_ITEM', '$.references[0].item'),
                 ([ref('a1', '2026-03-01T12:00:00'), ref('a1', '2026-03-01T12:00:01')], 'DUPLICATE_REFERENCE', '$.references[1].item'),
                 ([{'item': 'a1', 'trueLocal': '2026-03-01T12:00:00'}], 'REFERENCE_INVALID', '$.references[0].trueOffset'),
                 ([{'item': 'a1', 'trueLocal': '2026-03-01T12:00:00', 'trueOffset': '+01:00', 'trueUtc': '2026-03-01T11:00:00Z'}], 'REFERENCE_INVALID', '$.references[0]'),
                 ([{'item': 'a1', 'trueUtc': '2026-03-01T11:00:00'}], 'REFERENCE_INVALID', '$.references[0]'),
                 ([ref('a1', '2016-12-31T23:59:60')], 'LEAP_SECOND_UNSUPPORTED', '$.references[0]'),
                 ([ref('a1', '2026-03-01T12:00')], 'REFERENCE_INVALID', '$.references[0]'),
                 ([ref('a1', '2026-03-01T12:00:00', '-00:00')], 'REFERENCE_INVALID', '$.references[0]')]
        for refs, code, at in cases:
            self.assertEqual(problem(cm.reconcile, items, {'references': refs}), (code, at), refs)
        self.assertEqual(problem(cm.reconcile, items, {'assumedOffsets': [{'group': 'nope', 'offset': '+01:00'}]})[0], 'GROUP_MEMBERSHIP_INVALID')
        self.assertEqual(problem(cm.reconcile, items, {'assumeCorrect': ['nope']})[0], 'GROUP_MEMBERSHIP_INVALID')
        self.assertEqual(problem(cm.reconcile, items, {'simultaneous': [{'items': ['a1', 'zz']}]})[0], 'UNKNOWN_ITEM')
        self.assertEqual(problem(cm.reconcile, items, {'references': [ref('a1', '2026-03-01T12:00:00')] * 257})[0], 'INVALID_ARGUMENT')

    def test_trueUtc_reference_equals_trueLocal_reference(self):
        items = [item('a1', '2026-03-01T12:00:00')]
        a = cm.reconcile(items, {'references': [ref('a1', '2026-03-01T12:00:05')]})
        b = cm.reconcile(items, {'references': [{'item': 'a1', 'trueUtc': '2026-03-01T11:00:05Z'}]})
        self.assertEqual(a['references'][0]['instantSkewSeconds'], b['references'][0]['instantSkewSeconds'])
        self.assertEqual(b['references'][0]['wallSkewSeconds'], None)

    def test_conflict_flags_pass_through(self):
        report = cm.reconcile([item('a1', '2026-03-01T12:00:00', timeConflict=True, subSecondConflict=True)], {})
        self.assertEqual(by_id(report)['a1']['findings'], ['timeSourcesConflict', 'subSecondConflict'])


class ReviewFindings(unittest.TestCase):
    """Regression cases of the independent early review (E3R-1 to E3R-4 and the clock-related P3 items); every number is a hand-derived literal."""

    def drift_items(self):
        # camera A: recorded 10:00:00 true 10:00:00 (skew 0) and recorded 20:01:40 true 20:00:00 (skew 100 after 36100 recorded seconds): rate 100/36100 s per s,
        # so at a3 (recorded 15:00:50, 18050 s after the first reference) the skew is exactly 50 s and a3 truly happened at 15:00:00
        return [item('a1', '2026-03-01T10:00:00'), item('a2', '2026-03-01T20:01:40'), item('a3', '2026-03-01T15:00:50'), item('b1', '2026-03-01T15:00:00', device=dev('B', 'N'))]

    def drift_spec(self, **extra):
        return {'model': 'linearDrift', 'maxDriftRate': '0.01', 'toleranceSeconds': '2', 'references': [ref('a1', '2026-03-01T10:00:00'), ref('a2', '2026-03-01T20:00:00')],
                'simultaneous': [{'items': ['a3', 'b1'], 'toleranceSeconds': '1'}], **extra}

    def test_E3R1_a_drift_anchor_propagates_its_skew_at_the_edge_instant_not_its_intercept(self):
        report = cm.reconcile(self.drift_items(), self.drift_spec())
        b = group(report, 'dev2')
        self.assertEqual((b['state'], b['anchoredBy'], b['model'], b['skewSeconds']), ('anchored', 'path', 'constant', '0'))      # B's clock is right: b1 and a3 are the same moment
        rows = by_id(report)
        self.assertEqual((rows['a3']['skewSeconds'], rows['a3']['proposedLocal']), ('50', '2026-03-01T15:00:00'))
        self.assertEqual((rows['b1']['skewSeconds'], rows['b1']['proposedLocal']), ('0', '2026-03-01T15:00:00'))

    def test_E3R1_the_edge_endpoint_is_evaluated_in_both_directions(self):
        # the same relation read from the other side: B is the reference anchor (skew +7 at b1) and A (drift-free here) receives skew_a(a3) = 7 + (a3 - b1) = 7 + 50
        items = [item('a3', '2026-03-01T15:00:50'), item('b1', '2026-03-01T15:00:00', device=dev('B', 'N'))]
        report = cm.reconcile(items, {'references': [ref('b1', '2026-03-01T14:59:53')], 'simultaneous': [{'items': ['a3', 'b1']}]})
        self.assertEqual((group(report, 'dev1')['skewSeconds'], group(report, 'dev1')['anchoredBy'], group(report, 'dev2')['skewSeconds']), ('57', 'path', '7'))

    def test_E3R1_an_edge_outside_the_drift_span_anchors_nothing(self):
        items = self.drift_items() + [item('a9', '2026-03-01T21:00:00'), item('c1', '2026-03-01T21:00:00', device=dev('C', 'O'))]
        report = cm.reconcile(items, self.drift_spec(simultaneous=[{'items': ['a9', 'c1']}]))
        self.assertEqual(group(report, 'dev3')['state'], 'insufficient')
        self.assertEqual([(e['state'], e.get('code')) for e in report['edges']], [('unusable', 'outsideReferenceSpan')])
        allowed = cm.reconcile(items, self.drift_spec(simultaneous=[{'items': ['a9', 'c1']}], maxDriftExtrapolationSeconds=4000))
        self.assertEqual(group(allowed, 'dev3')['state'], 'anchored')       # the declared extrapolation allowance makes the edge usable again

    def test_E3R1_two_edges_at_different_instants_disagree_only_when_the_drift_says_so(self):
        # a3-b1 gives B skew 0 at b1; a fourth item pair at 17:00:00 recorded: A's skew there is 7200+... = (36100-?) -> hand value 100*(25200)/36100 is not integral,
        # so use a time where the drift is exact: 10:00:00 + 18050 s (15:00:50, skew 50) and 10:00:00 + 36100 s (20:01:40, skew 100)
        items = self.drift_items() + [item('b2', '2026-03-01T20:01:40', device=dev('B', 'N'))]
        spec = self.drift_spec(simultaneous=[{'items': ['a3', 'b1'], 'toleranceSeconds': '1'}, {'items': ['a2', 'b2'], 'toleranceSeconds': '1'}])
        report = cm.reconcile(items, spec)
        # a2-b2: B's recorded instant equals a2's, so the skew B must have at b2 is A's at a2 = 100, but the first edge gave B a skew of 0: implied minus actual = +100 s
        cycle = next(c for c in report['cycles'])
        self.assertEqual((cycle['residualSeconds'], cycle['state']), ('100', 'conflicting'))
        self.assertTrue(all(g['state'] == 'conflicting' for g in report['groups']))

    def test_E3R2_assume_correct_does_not_hide_contradicting_references(self):
        items = [item('a1', '2026-03-01T12:00:00'), item('a2', '2026-03-01T13:00:00')]
        refs = [ref('a1', '2026-03-01T11:00:00'), ref('a2', '2026-03-01T11:30:00')]
        report = cm.reconcile(items, {'references': refs, 'assumeCorrect': ['dev1']})
        g = group(report, 'dev1')
        self.assertEqual((g['state'], g['code'], g['anchoredBy'], g['skewSeconds']), ('conflicting', 'ASSUMPTION_CONTRADICTED', None, None))
        self.assertEqual({r['item']: r['residualSeconds'] for r in g['residuals']}, {'a1': '3600', 'a2': '5400'})
        self.assertTrue(all(i['proposedLocal'] is None for i in report['items']))
        # one consistent reference that contradicts the declaration is contradicted as well
        one = cm.reconcile(items, {'references': refs[:1], 'assumeCorrect': ['dev1']})
        self.assertEqual((group(one, 'dev1')['state'], group(one, 'dev1')['code']), ('conflicting', 'ASSUMPTION_CONTRADICTED'))

    def test_E3R2_assume_correct_with_references_inside_the_tolerance_lists_them_as_residuals(self):
        items = [item('a1', '2026-03-01T12:00:00')]
        report = cm.reconcile(items, {'references': [ref('a1', '2026-03-01T12:00:01')], 'assumeCorrect': ['dev1']})
        g = group(report, 'dev1')
        self.assertEqual((g['state'], g['anchoredBy'], g['skewSeconds'], g['spreadSeconds']), ('anchored', 'assumeCorrect', '0', '0'))
        self.assertEqual(g['residuals'], [{'item': 'a1', 'residualSeconds': '-1'}])

    def test_E3R4_a_proposal_outside_the_supported_years_is_a_per_item_finding(self):
        # a1 is a reference with skew +10 s (recorded 10 s after the truth); the same camera's other photos are 1900-01-01T00:00:00 (true: 23:59:50 on 1899-12-31) and 2100-12-31T23:59:55 (true -10 s)
        items = [item('a1', '2026-03-01T12:00:10', offset='+00:00'), item('old', '1900-01-01T00:00:00', offset='+00:00'), item('new', '2100-12-31T23:59:59', offset='+00:00'),
                 item('edge', '1900-01-01T05:00:00', offset='+14:00')]
        report = cm.reconcile(items, {'references': [ref('a1', '2026-03-01T12:00:00', '+00:00')]})
        rows = by_id(report)
        self.assertEqual((rows['old']['proposedLocal'], rows['old']['proposedInstant']), (None, '1899-12-31T23:59:50'))
        self.assertIn('TIME_OUT_OF_RANGE', rows['old']['findings'])
        self.assertEqual(rows['new']['proposedLocal'], '2100-12-31T23:59:49')
        # a valid file whose UTC instant is before 1900 (05:00 at +14:00) proposes a local time inside the range and an instant outside it: no exception
        self.assertEqual((rows['edge']['proposedLocal'], rows['edge']['proposedInstant']), ('1900-01-01T04:59:50', '1899-12-31T14:59:50'))
        high = cm.reconcile([item('a1', '2026-03-01T12:00:00', offset='+00:00'), item('late', '2100-12-31T23:59:59', offset='+00:00')], {'references': [ref('a1', '2026-03-01T12:00:10', '+00:00')]})
        self.assertEqual((by_id(high)['late']['proposedLocal'], by_id(high)['late']['proposedInstant']), (None, '2101-01-01T00:00:09'))
        self.assertIn('TIME_OUT_OF_RANGE', by_id(high)['late']['findings'])

    def test_P3_an_unreadable_or_conflicting_recorded_offset_is_not_replaced_by_an_assumption(self):
        for state, finding in (('unreadable', 'offsetUnreadable'), ('unsupported', 'offsetUnreadable'), ('ambiguous', 'offsetConflict')):
            i = item('a1', '2026-03-01T12:00:00', offset=None)
            i['offsetState'] = state
            row = by_id(cm.reconcile([i], {'assumedOffsets': [{'group': 'dev1', 'offset': '+01:00'}]}))['a1']
            self.assertEqual((row['basis'], finding in row['findings']), ('offsetUnresolved', True), state)
        absent = item('a1', '2026-03-01T12:00:00', offset=None)
        absent['offsetState'] = 'absent'
        self.assertEqual(by_id(cm.reconcile([absent], {'assumedOffsets': [{'group': 'dev1', 'offset': '+01:00'}]}))['a1']['basis'], 'assumedOffset')

    def test_P3_a_simultaneity_with_an_ungroupable_member_names_the_identity_problem(self):
        bad = dev('A', serial='1', cameraMake={'state': 'ambiguous'})
        items = [item('a1', '2026-03-01T12:00:00'), item('x1', '2026-03-01T12:00:00', device=bad)]
        report = cm.reconcile(items, {'simultaneous': [{'items': ['a1', 'x1']}]})
        self.assertEqual([(e['state'], e['code'], e['items']) for e in report['edges']], [('unusable', 'DEVICE_IDENTITY_UNRESOLVED', ['x1'])])

    def test_P3_an_override_may_join_a_recorded_device_but_not_invent_a_reserved_id(self):
        bad = dev('A', serial='1', cameraMake={'state': 'ambiguous'})
        items = [item('a1', '2026-03-01T12:00:00'), item('x1', '2026-03-01T12:00:00', device=bad)]
        joined = cm.reconcile(items, {'groups': {'by': 'recordedDevice', 'itemOverrides': [{'item': 'x1', 'group': 'dev1'}]}})
        self.assertEqual(group(joined, 'dev1')['members'], ['a1', 'x1'])
        self.assertEqual(joined['findings'], [{'code': 'overrideJoinsRecordedDevice', 'item': 'x1', 'group': 'dev1'}])
        self.assertEqual(problem(cm.reconcile, items, {'groups': {'by': 'recordedDevice', 'itemOverrides': [{'item': 'x1', 'group': 'dev7'}]}})[0], 'GROUP_MEMBERSHIP_INVALID')
        fresh = cm.reconcile(items, {'groups': {'by': 'recordedDevice', 'itemOverrides': [{'item': 'x1', 'group': 'camera_x'}]}})
        self.assertEqual(group(fresh, 'camera_x')['members'], ['x1'])


class WriterReviewRegressions(unittest.TestCase):
    """E3W-2 (a drift skew belongs to an instant) and E3W-3 (a path never overwrites a group's own contrary references); every number is hand-computed."""

    def drift_items(self):
        return [item('r1', '2026-03-01T10:00:10', offset='+00:00'), item('r2', '2026-03-01T20:00:45', offset='+00:00'), item('o', '2026-03-01T15:00:38', offset='+00:00'),
                item('w', '2026-03-01T15:00:38', offset=None)]

    def test_E3W2_an_item_with_no_recorded_instant_has_no_drift_skew_and_never_the_intercept(self):
        spec = {'references': [{'item': 'r1', 'trueUtc': '2026-03-01T10:00:00Z'}, {'item': 'r2', 'trueUtc': '2026-03-01T20:00:00Z'}], 'model': 'linearDrift'}
        report, exact = cm.reconcile_exact(self.drift_items(), spec)
        self.assertEqual(group(report, 'dev1')['state'], 'anchored')
        self.assertEqual((exact['w']['skew'], exact['w']['model']), (None, 'linearDrift'))        # the intercept (10 s at t0) is not w's skew
        self.assertIsNotNone(exact['o']['skew'])
        self.assertNotEqual(exact['o']['skew'], 10)
        row = by_id(report)['w']
        self.assertEqual((row['skewSeconds'], row['proposedLocal']), (None, None))                # the report and the correction agree: nothing is proposed

    def test_a_constant_model_wall_only_item_is_corrected_only_by_a_wall_skew_the_references_give(self):
        spec = {'references': [{'item': 'r1', 'trueUtc': '2026-03-01T10:00:00Z'}]}
        report, exact = cm.reconcile_exact(self.drift_items(), spec)
        self.assertEqual((exact['w']['skew'], exact['w']['wallSkew']), (None, None))
        self.assertEqual((by_id(report)['w']['skewSeconds'], by_id(report)['w']['proposedLocal']), (None, None))
        wall = {'references': [ref('r1', '2026-03-01T10:00:00', '+00:00')]}
        report, exact = cm.reconcile_exact(self.drift_items(), wall)
        self.assertEqual((exact['w']['skew'], str(exact['w']['wallSkew'])), (None, '10'))          # a trueLocal reference gives a constant wall-clock skew: 15:00:38 -> 15:00:28
        self.assertEqual((by_id(report)['w']['skewSeconds'], by_id(report)['w']['proposedLocal']), ('10', '2026-03-01T15:00:28'))

    def test_E3W3_a_path_does_not_overwrite_the_contrary_references_of_the_group_it_anchors(self):
        items = [item('a1', '2026-03-01T10:00:00', offset='+00:00', device=dev('A', serial='1')), item('a2', '2026-03-01T20:00:00', offset='+00:00', device=dev('A', serial='1')),
                 item('a3', '2026-03-01T15:00:00', offset='+00:00', device=dev('A', serial='1')),
                 item('b1', '2026-03-01T15:00:00', offset='+00:00', device=dev('B', serial='2')), item('b2', '2026-03-01T16:00:00', offset='+00:00', device=dev('B', serial='2'))]
        spec = {'references': [{'item': 'a1', 'trueUtc': '2026-03-01T10:00:00Z'}, {'item': 'a2', 'trueUtc': '2026-03-01T20:00:00Z'}, {'item': 'b2', 'trueUtc': '2026-03-01T15:00:00Z'}],
                'simultaneous': [{'items': ['a3', 'b1'], 'toleranceSeconds': '1'}], 'model': 'linearDrift'}
        report = cm.reconcile(items, spec)
        b = group(report, 'dev2')
        self.assertEqual((b['state'], b['code']), ('conflicting', 'REFERENCE_CONTRADICTED'))
        self.assertEqual(b['residuals'], [{'item': 'b2', 'residualSeconds': '3600'}])              # b2's declared true time is an hour before what the path says
        self.assertIsNone(by_id(report)['b2']['proposedLocal'])
        # consistent evidence anchors the group by the path, clears the stale reason and publishes the residual
        agree = dict(spec, references=spec['references'][:2] + [{'item': 'b2', 'trueUtc': '2026-03-01T16:00:00Z'}])
        b = group(cm.reconcile(items, agree), 'dev2')
        self.assertEqual((b['state'], b['anchoredBy'], b['residuals']), ('anchored', 'path', [{'item': 'b2', 'residualSeconds': '0'}]))
        self.assertIsNone(b['reason'])


if __name__ == '__main__':
    unittest.main()
