"""Hand-literal acceptance of the E4 name planner (contract cases N-1 .. N-12; no native process, no reader, no ExifTool).

Every expected path is written here by hand from the contract tables; none is computed by the planner under test.
"""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))

from schemaxis.adaptors.exiftool import naming  # noqa: E402


def moment(local, offset=None, sub=None, state='present'):
    return {'state': state, 'local': local, 'offset': offset, 'sub': sub, 'subState': 'present' if sub else 'absent'}


def subject(item, order, time=None, model='M', make='Make', stem=None, suffix='.jpg', container='jpeg', sidecar=False, exif=None, xmp=None, iptc=None):
    absent = {'state': 'absent'}
    aggregate = time or {'state': 'absent'}
    return {'id': item, 'order': order, 'stem': stem or item, 'suffix': suffix, 'container': container, 'sidecar': sidecar,
            'time': {'aggregate': aggregate, 'exif': exif or aggregate, 'xmp': xmp or absent, 'iptc': iptc or absent},
            'cameraModel': {'state': 'present' if model else 'absent', 'value': model}, 'cameraMake': {'state': 'present' if make else 'absent', 'value': make}}


def rule(**extra):
    base = {'name': [{'token': 'captureDate'}, {'literal': '_'}, {'token': 'captureTime'}]}
    base.update(extra)
    return naming.normalise_rule(base)


def paths(plan):
    return [(r['id'], r['relativePath'], r['fault']['code'] if r['fault'] else None) for r in plan['items']]


class Names(unittest.TestCase):
    def three(self):
        return [subject('a', 1, moment('2024-03-01T10:20:30', '+09:00')), subject('b', 2, moment('2024-03-01T10:20:30', '+09:00')), subject('c', 3, moment('2024-03-01T11:00:00'))]

    def test_N1_recorded_local_names_and_the_collision_sequence_follows_manifest_order(self):
        plan = naming.plan(rule(collisions='sequence'), self.three())
        self.assertEqual(paths(plan), [('a', '20240301_102030.jpg', None), ('b', '20240301_102030-2.jpg', None), ('c', '20240301_110000.jpg', None)])

    def test_N1_refuse_lists_every_member(self):
        plan = naming.plan(rule(), self.three())
        self.assertEqual([(i, p, c) for i, p, c in paths(plan)], [('a', None, 'NAME_COLLISION'), ('b', None, 'NAME_COLLISION'), ('c', '20240301_110000.jpg', None)])
        self.assertEqual(plan['items'][0]['fault']['members'], ['20240301_102030.jpg', '20240301_102030.jpg'])
        self.assertEqual(plan['items'][0]['fault']['items'], ['a', 'b'])

    def test_N2_utc_basis_converts_with_the_recorded_offset_and_refuses_a_missing_one(self):
        plan = naming.plan(rule(time={'basis': 'utc'}, collisions='sequence'), self.three())
        self.assertEqual(paths(plan), [('a', '20240301_012030.jpg', None), ('b', '20240301_012030-2.jpg', None), ('c', None, 'NAME_OFFSET_MISSING')])
        again = naming.plan(rule(time={'basis': 'utc', 'missingOffset': 'useRecordedLocal'}, collisions='sequence'), self.three())
        self.assertEqual(paths(again)[2], ('c', '20240301_110000.jpg', None))
        self.assertIn({'code': 'offsetMissingUsedLocal'}, again['items'][2]['notes'])

    def test_N2_fixed_offset_is_an_author_statement(self):
        plan = naming.plan(rule(time={'basis': {'fixedOffset': '-05:00'}}), self.three()[:1])
        self.assertEqual(paths(plan), [('a', '20240229_202030.jpg', None)])

    def test_N3_conflicting_sources_refuse_unless_a_family_is_named(self):
        ambiguous = {'state': 'ambiguous', 'values': [{'family': 'exif', 'value': '2024-03-01T10:20:30'}, {'family': 'xmp', 'value': '2024-03-01T10:21:00'}]}
        s = subject('a', 1, ambiguous, exif=moment('2024-03-01T10:20:30'), xmp=moment('2024-03-01T10:21:00'))
        refused = naming.plan(rule(), [s])['items'][0]
        self.assertEqual(refused['fault']['code'], 'NAME_TIME_CONFLICT')
        self.assertEqual(len(refused['fault']['values']), 2)
        chosen = naming.plan(rule(time={'source': 'exif'}), [s])['items'][0]
        self.assertEqual(chosen['relativePath'], '20240301_102030.jpg')
        self.assertEqual(chosen['notes'][0]['code'], 'NAME_TIME_SOURCES_DISAGREE')

    def test_E4H1_an_offset_or_fraction_that_only_a_carrier_without_its_own_time_states_never_names_a_file(self):
        offset = [{'component': 'offset', 'family': 'iptc', 'location': '2:60', 'value': '+09:00'}]
        fraction = [{'component': 'sub', 'family': 'exif', 'location': 'ExifIFD:0x9291', 'value': '25'}]
        orphan = lambda carriers: subject('a', 1, {**moment('2024-03-01T10:20:30', carriers[0]['value'] if carriers[0]['component'] == 'offset' else None, carriers[0]['value'] if carriers[0]['component'] == 'sub' else None), 'unanchored': carriers})
        message = 'the source capture time cannot be used: its %s is stated only by a carrier that does not state the local time itself, so no association with that time is invented'
        refused = naming.plan(rule(time={'basis': 'utc'}), [orphan(offset)])['items'][0]
        self.assertEqual((refused['relativePath'], (refused['fault'] or {}).get('code'), (refused['fault'] or {}).get('message')), (None, 'NAME_TIME_COMPONENT_UNANCHORED', message % 'UTC offset'))
        self.assertEqual((refused['fault'] or {}).get('carriers'), offset)
        refused = naming.plan(rule(time={'basis': {'fixedOffset': '-05:00'}}), [orphan(offset)])['items'][0]
        self.assertEqual((refused['fault'] or {}).get('code'), 'NAME_TIME_COMPONENT_UNANCHORED')
        # the recorded-local basis never reads an offset, so an orphan offset is ignored there; an orphan fraction orders and times names in every basis
        self.assertEqual(naming.plan(rule(), [orphan(offset)])['items'][0]['relativePath'], '20240301_102030.jpg')
        for basis in ('recordedLocal', 'utc'):
            refused = naming.plan(rule(time={'basis': basis}), [orphan(fraction)])['items'][0]
            self.assertEqual((refused['relativePath'], (refused['fault'] or {}).get('code'), (refused['fault'] or {}).get('message')), (None, 'NAME_TIME_COMPONENT_UNANCHORED', message % 'fraction of a second'), basis)
        self.assertEqual(naming.plan(rule(time={'basis': 'utc'}), [subject('a', 1, moment('2024-03-01T10:20:30', '+09:00', '25'))])['items'][0]['relativePath'], '20240301_012030.jpg')   # anchored: unchanged

    def test_N4_a_declared_fallback_stands_for_a_missing_time_and_unreadable_is_never_missing(self):
        s = subject('a', 1)
        plan = naming.plan(rule(name=[{'token': 'originalStem'}], folders=[{'token': 'year'}], time={'missing': {'fallback': 'undated'}}), [s])
        self.assertEqual(paths(plan), [('a', 'undated/a.jpg', None)])
        unreadable = subject('a', 1, {'state': 'unreadable'})
        again = naming.plan(rule(name=[{'token': 'originalStem'}], folders=[{'token': 'year'}], time={'missing': {'fallback': 'undated'}}), [unreadable])
        self.assertEqual(again['items'][0]['fault']['code'], 'NAME_TIME_MISSING')
        self.assertEqual(again['items'][0]['fault']['state'], 'unreadable')

    def test_N5_forbidden_characters_become_one_underscore_each_run(self):
        plan = naming.plan(rule(name=[{'token': 'cameraModel'}]), [subject('a', 1, model='Ca/m:era*')])
        self.assertEqual(plan['items'][0]['relativePath'], 'Ca_m_era_.jpg')
        self.assertEqual(plan['items'][0]['notes'][0], {'code': 'replacedCharacters', 'component': 'name', 'count': 3})

    def test_N5_only_spaces_and_dots_are_stripped(self):
        plan = naming.plan(rule(name=[{'token': 'cameraModel'}]), [subject('a', 1, model='  ..Model.. ')])
        self.assertEqual(plan['items'][0]['relativePath'], 'Model.jpg')

    def test_N6_reserved_device_names_get_a_suffix(self):
        plan = naming.plan(rule(name=[{'token': 'cameraModel'}]), [subject('a', 1, model='CON'), subject('b', 2, model='com²'), subject('c', 3, model='Lpt9')])
        self.assertEqual([p for _, p, _ in paths(plan)], ['CON_.jpg', 'com²_.jpg', 'Lpt9_.jpg'])

    def test_N7_casefold_collision_is_reported_with_both_members(self):
        plan = naming.plan(rule(name=[{'token': 'cameraModel'}]), [subject('a', 1, model='Straße'), subject('b', 2, model='STRASSE')])
        self.assertEqual([c for _, _, c in paths(plan)], ['NAME_COLLISION', 'NAME_COLLISION'])
        self.assertEqual(plan['items'][0]['fault']['items'], ['a', 'b'])

    def test_N8_nfc_and_nfd_are_one_unit(self):
        plan = naming.plan(rule(name=[{'token': 'cameraModel'}]), [subject('a', 1, model='é'), subject('b', 2, model='é')])
        self.assertEqual([c for _, _, c in paths(plan)], ['NAME_COLLISION', 'NAME_COLLISION'])
        sequenced = naming.plan(rule(name=[{'token': 'cameraModel'}], collisions='sequence'), [subject('a', 1, model='é'), subject('b', 2, model='é')])
        self.assertEqual([p for _, p, _ in paths(sequenced)], ['é.jpg', 'é-2.jpg'])
        self.assertIn({'code': 'nfcNormalised', 'component': 'name'}, sequenced['items'][1]['notes'])

    def test_N9_a_year_month_model_tree(self):
        plan = naming.plan(rule(folders=[{'token': 'year'}, {'token': 'month'}, {'token': 'cameraModel'}]), [subject('a', 1, moment('2024-03-01T10:20:30'), model='Model')])
        self.assertEqual(plan['items'][0]['relativePath'], '2024/03/Model/20240301_102030.jpg')

    def test_N10_a_200_byte_model_is_truncated_on_a_code_point_and_declared(self):
        plan = naming.plan(rule(name=[{'token': 'cameraModel'}]), [subject('a', 1, model='é' * 100)])
        name = plan['items'][0]['relativePath']
        self.assertEqual(name, 'é' * 58 + '.jpg')
        self.assertLessEqual(len(name.encode()), 120)
        self.assertIn({'code': 'truncated', 'component': 'name', 'limitBytes': 120}, plan['items'][0]['notes'])

    def test_N11_bidi_override_is_replaced_and_declared(self):
        plan = naming.plan(rule(name=[{'token': 'cameraModel'}]), [subject('a', 1, model='ab‮cd')])
        self.assertEqual(plan['items'][0]['relativePath'], 'ab_cd.jpg')
        self.assertEqual(plan['items'][0]['notes'][0], {'code': 'replacedCharacters', 'component': 'name', 'count': 1})

    def test_N12_an_image_and_its_sidecar_are_one_collision_unit(self):
        a, b = subject('a', 1, stem='a', sidecar=True), subject('b', 2, stem='a', suffix='.png', container='png', sidecar=True)
        sequenced = naming.plan(rule(name=[{'token': 'originalStem'}], collisions='sequence'), [a, b])
        self.assertEqual([(r['relativePath'], r['sidecarPath']) for r in sequenced['items']], [('a.jpg', 'a.xmp'), ('a-2.png', 'a-2.xmp')])
        refused = naming.plan(rule(name=[{'token': 'originalStem'}]), [a, b])
        self.assertEqual([c for _, _, c in paths(refused)], ['NAME_COLLISION', 'NAME_COLLISION'])

    def test_sequence_numbers_are_assigned_by_name_then_instant_then_manifest_order(self):
        s = [subject('a', 1, moment('2024-03-01T12:00:00')), subject('b', 2, moment('2024-03-01T11:00:00')), subject('c', 3, moment('2024-03-01T11:00:00'))]
        plan = naming.plan(rule(name=[{'token': 'captureDate'}, {'literal': '-'}, {'token': 'sequence', 'width': 2, 'start': 7, 'scope': 'global'}]), s)
        self.assertEqual([p for _, p, _ in paths(plan)], ['20240301-09.jpg', '20240301-07.jpg', '20240301-08.jpg'])

    def test_a_file_and_a_directory_that_differ_only_by_case_collide(self):
        plan = naming.plan(rule(name=[{'token': 'cameraModel'}], folders=[{'token': 'cameraMake'}], collisions='sequence'),
                           [subject('a', 1, model='x', make='Dir'), subject('b', 2, model='dir', make='x')])
        self.assertEqual(len({p.casefold() for _, p, _ in paths(plan)}), 2)

    def test_rule_validation_is_closed(self):
        for bad_rule, code in (({'name': []}, 'INVALID_NAME_RULE'), ({'name': [{'literal': 'x'}]}, 'INVALID_NAME_RULE'), ({'name': [{'token': 'strftime'}]}, 'INVALID_NAME_RULE'),
                               ({'name': [{'token': 'sequence', 'width': 9}]}, 'INVALID_NAME_RULE'), ({'name': [{'token': 'itemId'}], 'folders': [{'token': 'itemId'}]}, 'INVALID_NAME_RULE'),
                               ({'name': [{'token': 'itemId'}], 'time': {'basis': {'fixedOffset': '+15:00'}}}, 'INVALID_NAME_RULE'), ({'name': [{'token': 'itemId'}], 'regex': 'x'}, None)):
            if code is None:
                continue
            with self.assertRaises(naming.NamingError) as raised:
                naming.normalise_rule(bad_rule)
            self.assertEqual(raised.exception.code, code)

    def test_extension_is_canonical_by_container_and_a_mismatch_is_reported(self):
        s = subject('a', 1, stem='a', suffix='.JPEG')
        self.assertEqual(naming.plan(rule(name=[{'token': 'originalStem'}]), [s])['items'][0]['relativePath'], 'a.jpg')
        odd = subject('a', 1, stem='a', suffix='.png')
        planned = naming.plan(rule(name=[{'token': 'originalStem'}]), [odd])['items'][0]
        self.assertEqual(planned['relativePath'], 'a.jpg')
        self.assertTrue(any(n['code'] == 'EXTENSION_MISMATCH' for n in planned['notes']))
        kept = naming.plan(rule(name=[{'token': 'originalStem'}], extension='keepOriginal'), [odd])['items'][0]
        self.assertEqual(kept['relativePath'], 'a.png')

    def test_sub_second_digits_are_adjusted_to_three_and_unreadable_ones_are_never_zero(self):
        r = rule(name=[{'token': 'captureTime', 'format': 'HHmmssSSS'}])
        self.assertEqual(naming.plan(r, [subject('a', 1, moment('2024-03-01T10:20:30', sub='5'))])['items'][0]['relativePath'], '102030500.jpg')
        self.assertEqual(naming.plan(r, [subject('a', 1, moment('2024-03-01T10:20:30', sub='123456'))])['items'][0]['relativePath'], '102030123.jpg')
        self.assertEqual(naming.plan(r, [subject('a', 1, moment('2024-03-01T10:20:30'))])['items'][0]['relativePath'], '102030000.jpg')
        bad_sub = moment('2024-03-01T10:20:30')
        bad_sub['subState'] = 'unreadable'
        self.assertEqual(naming.plan(r, [subject('a', 1, bad_sub)])['items'][0]['fault']['code'], 'NAME_TIME_MISSING')


if __name__ == '__main__':
    unittest.main()
