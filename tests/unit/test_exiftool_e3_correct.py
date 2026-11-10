"""Tests of ``correctTime``: document planning, the per-item time plan, and (with a real ExifTool 13.55 through SCHEMAXIS_EXIFTOOL) genuine writes, the
three proofs recomputed by verify, truthful partial outcomes, plan-only runs and plan application, and exact semantic mutants.

Every expected value is a literal derived by hand in this file (calendar arithmetic, skews in seconds, the native text forms), never taken from the code under
test or from ExifTool output. Fixtures are synthetic JPEGs built by ``exiftool_e3_fixtures`` in private temporary directories.
"""
import copy
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(ROOT / 'tools'))
sys.path.insert(0, str(ROOT / 'tests/unit'))

import exiftool_e3_fixtures as fx  # noqa: E402
from schemaxis.adaptors.exiftool import adaptor, catalogue, containers, e3read, e3time, e3write, editing, records, timecalc as tc  # noqa: E402
from schemaxis.core.faults import SchemaxisError  # noqa: E402

V = 'schemaxis.exiftool/1'


def items(root, names):
    return {'items': [{'id': n, 'path': str(root / (n + '.jpg'))} for n in names]}


def doc(operation, media, **rest):
    return {'version': V, 'operation': operation, 'media': media, **rest}


def fault_of(call):
    try:
        call()
    except SchemaxisError as error:
        return error.fault
    raise AssertionError('no fault')


def fields_of(data):
    payloads = records.Payloads(containers.locate(data))
    reader = records.Record(payloads, catalogue.VERSION_E3)
    return {name: reader.field(name) for name in e3read.field_names('reconcileTime')}, payloads


def group(data, name, delta='0', set_offset=None, assumed=None, **policies):
    fields, payloads = fields_of(data)
    return e3time.plan_group(name, fields, payloads, tc.seconds_ns(delta), set_offset, assumed, {'sourceConflicts': 'refuse', 'subSecond': 'addIfNeeded', **policies}, '$.items[0]')


def writes(plan):
    return [(n, v) for t in plan['targets'] if t['changes'] or t.get('forced') for n, v in t['writes']]


def refusal(call):
    from schemaxis.adaptors.exiftool import edits
    try:
        call()
    except edits.Refusal as error:
        return error.code
    raise AssertionError('no refusal')


class Planning(unittest.TestCase):
    """The authored document: defaults made explicit, exact normalisation and exact ``$`` locations."""

    BASE = doc('correctTime', {'items': [{'id': 'a1', 'path': '/x/a1.jpg'}, {'id': 'b1', 'path': '/x/b1.jpg'}]}, corrections=[{'group': 'dev1', 'shift': {'seconds': '1'}}])

    def plan(self, **change):
        document = copy.deepcopy(self.BASE)
        document.update(change)
        return adaptor.plan(document)

    def test_defaults_are_explicit_and_the_operation_selects_the_internal_view(self):
        p = self.plan()
        self.assertEqual((p['operation'], p['apply'], p['catalogue']['version']), ('correctTime', 'write', 'schemaxis.exiftool.fields/3'))
        self.assertEqual(p['e3']['timeFields'], ['captured', 'digitized'])        # modified is an edit time and is shifted only on request
        self.assertEqual(p['e3']['policies'], {'sourceConflicts': 'refuse', 'subSecond': 'addIfNeeded', 'uncorrectedItems': 'copyUnchanged'})
        self.assertEqual(p['writes']['version'], 'schemaxis.exiftool.writes/3')
        self.assertEqual(p['e3']['arguments']['corrections'], [{'group': 'dev1', 'shift': {'seconds': '1'}}])
        self.assertNotIn('timeLocation', json.dumps(p))

    def test_shift_forms_normalise_to_one_exact_seconds_value(self):
        # 1 day - 2 hours + 3.25 s = 86400 - 7200 + 3.25
        p = self.plan(corrections=[{'group': 'dev1', 'shift': {'days': 1, 'hours': -2, 'minutes': 0, 'seconds': '3.25'}}])
        self.assertEqual(p['e3']['corrections'][0]['shift'], {'seconds': '79203.25'})
        self.assertEqual(self.plan(corrections=[{'group': 'dev1', 'shift': {'seconds': '-3725.5'}}])['e3']['corrections'][0]['shift'], {'seconds': '-3725.5'})

    def test_exact_faults(self):
        cases = [(dict(corrections=[{'group': 'dev1', 'shift': {'seconds': '3155760001'}}]), 'SHIFT_OUT_OF_RANGE', '$.corrections[0].shift'),
                 (dict(corrections=[{'group': 'dev1', 'shift': {'seconds': '1'}}, {'group': 'dev1', 'shift': {'seconds': '2'}}]), 'INVALID_ARGUMENT', '$.corrections[1].group'),
                 (dict(corrections=[{'group': 'dev1', 'from': 'references', 'shift': {'seconds': '1'}}]), 'INVALID_ARGUMENT', '$.corrections[0]'),
                 (dict(corrections=[{'group': 'dev1'}]), 'INVALID_ARGUMENT', '$.corrections[0]'),
                 (dict(corrections=[{'group': 'dev1', 'setOffset': {'offset': '+15:00', 'keep': 'instant'}}]), 'INVALID_ARGUMENT', '$.corrections[0].setOffset.offset'),
                 (dict(corrections=[{'group': 'dev 1', 'shift': {'seconds': '1'}}]), 'GROUP_MEMBERSHIP_INVALID', '$.corrections[0].group'),
                 (dict(references=[{'item': 'a1', 'trueLocal': '2016-12-31T23:59:60', 'trueOffset': '+00:00'}]), 'LEAP_SECOND_UNSUPPORTED', '$.references[0]'),
                 (dict(references=[{'item': 'zz', 'trueUtc': '2026-03-01T00:00:00Z'}]), 'UNKNOWN_ITEM', '$.references[0].item'),
                 (dict(timeFields=[]), 'INVALID_ARGUMENT', '$.arguments.timeFields'),             # a declaration-level fault: the framework's own location
                 (dict(policies={'preferFamily': 'exif'}), 'INVALID_ARGUMENT', '$.policies.preferFamily'),
                 (dict(policies={'sourceConflicts': 'preferFamily'}), 'INVALID_ARGUMENT', '$.policies.preferFamily'),
                 (dict(policies={'subSecond': 'sometimes'}), 'INVALID_ARGUMENT', '$.arguments.policies.subSecond'),
                 (dict(groups={'by': 'declared', 'members': [{'group': 'x', 'items': ['a1', 'b1']}]}), 'GROUP_MEMBERSHIP_INVALID', '$.corrections[0].group')]
        for change, code, at in cases:
            f = fault_of(lambda: self.plan(**change))
            self.assertEqual((f.code, f.location), (code, at), change)

    def test_a_plan_carries_every_other_input_and_no_catalogue_or_flag_can_be_named(self):
        for extra in ({'corrections': self.BASE['corrections']}, {'groups': {'by': 'recordedDevice'}}):
            f = fault_of(lambda: self.plan(plan='/x/p.json', **extra))
            self.assertEqual((f.code, f.location), ('INVALID_ARGUMENT', '$.plan'))
        p = adaptor.plan(doc('correctTime', self.BASE['media'], plan='/x/p.json'))
        self.assertEqual(p['e3'], {'planFile': '/x/p.json'})
        for key in ('companions', 'catalogue', 'fields', 'config', 'args', 'expression'):
            f = fault_of(lambda: self.plan(**{key: 'x'}))
            self.assertEqual(f.code, 'UNKNOWN_ARGUMENT', key)
        self.assertEqual(fault_of(lambda: adaptor.plan(doc('correctTime', self.BASE['media'], plan='relative.json'))).code, 'INVALID_PHOTO_SOURCE')

    def test_the_schema_has_a_branch_without_native_names(self):
        schema = adaptor.schema()
        branch = next(b for b in schema['oneOf'] if b['properties']['operation'].get('const') == 'correctTime')
        self.assertIn('corrections', branch['properties'])
        text = json.dumps(branch).lower()
        for banned in ('tagname', 'perl', 'expression', 'alldates', '-api', 'geosync'):
            self.assertNotIn(banned, text)


class TimePlan(unittest.TestCase):
    """The per-item plan, from the independent reader of a hand-built capture: which sources are rewritten, to what, with which losses."""

    def test_T1_every_present_source_is_rewritten_and_the_iptc_fraction_is_a_declared_loss(self):
        plan = group(fx.full_time(), 'captured', '330.38')
        # 12:00:00.12 + 330.38 s = 12:05:30.50: the two recorded digits are kept ("50"), the date and the offset are unchanged and so are not written
        self.assertEqual(plan['before'], {'local': '2026-03-01T12:00:00', 'offset': '+01:00', 'fraction': '12'})
        self.assertEqual(plan['after'], {'local': '2026-03-01T12:05:30', 'offset': '+01:00', 'fraction': '50'})
        self.assertEqual(writes(plan), [('ExifIFD:DateTimeOriginal', '2026:03:01 12:05:30'), ('ExifIFD:SubSecTimeOriginal', '50'),
                                        ('XMP-photoshop:DateCreated', '2026-03-01T12:05:30.50+01:00'), ('IPTC:TimeCreated', '120530+0100')])
        self.assertEqual(plan['losses'], [{'key': 'IPTC:TimeCreated', 'reason': 'iptcFractionDropped', 'fraction': '50', 'treatment': 'truncatedToTheEarlierSecond'}])
        self.assertEqual(e3time.assignments([plan]), ['-n', '-ExifIFD:DateTimeOriginal=2026:03:01 12:05:30', '-ExifIFD:SubSecTimeOriginal=50',
                                                      '-XMP-photoshop:DateCreated=2026-03-01T12:05:30.50+01:00', '-IPTC:TimeCreated=120530+0100'])
        self.assertEqual(e3time.expectations([plan])[('capturedLocalE3', 'iptc', '2:55')], '2026-03-01T12:05:30')

    def test_T2_calendar_carries_are_exact(self):
        leap = group(fx.jpeg(dto='2024:02:28 23:59:59', sub=None), 'captured', '1')
        self.assertEqual(writes(leap), [('ExifIFD:DateTimeOriginal', '2024:02:29 00:00:00')])
        year = group(fx.jpeg(dto='2023:12:31 23:59:59', sub='9'), 'captured', '0.2')
        # .9 + .2 carries one second: 2024-01-01T00:00:00.1, and the single recorded digit stays one digit
        self.assertEqual((year['after']['local'], year['after']['fraction']), ('2024-01-01T00:00:00', '1'))
        self.assertEqual(writes(year), [('ExifIFD:DateTimeOriginal', '2024:01:01 00:00:00'), ('ExifIFD:SubSecTimeOriginal', '1')])

    def test_T3_there_is_no_february_29_in_2023(self):
        plan = group(fx.jpeg(dto='2023:02:28 12:00:00', sub=None), 'captured', '86400')
        self.assertEqual(plan['after']['local'], '2023-03-01T12:00:00')

    def test_digits_are_extended_never_rounded(self):
        plan = group(fx.jpeg(dto='2026:03:01 12:00:00', sub='5'), 'captured', '0.25')
        self.assertEqual((plan['after']['fraction'], plan['infos']), ('75', ['subSecondDigitsExtended']))
        self.assertEqual(writes(plan)[-1], ('ExifIFD:SubSecTimeOriginal', '75'))
        zero = group(fx.jpeg(dto='2026:03:01 12:00:00', sub='12'), 'captured', '0.88')
        self.assertEqual((zero['after']['local'], zero['after']['fraction']), ('2026-03-01T12:00:01', '00'))      # .12 + .88 = 1.00: the two digits stay

    def test_a_fractional_shift_adds_a_fraction_only_where_one_can_be_held(self):
        both = group(fx.jpeg(dto='2026:03:01 12:00:00', sub=None, xmp=fx.xmp_properties(captured='2026-03-01T12:00:00+01:00'), iptc=[(2, 55, '20260301'), (2, 60, '120000+0100')]), 'captured', '0.5')
        self.assertEqual(writes(both), [('ExifIFD:SubSecTimeOriginal', '5'), ('XMP-photoshop:DateCreated', '2026-03-01T12:00:00.5+01:00'), ('IPTC:TimeCreated', '120000+0100')][:2])
        self.assertEqual([l['reason'] for l in both['losses']], ['iptcFractionDropped'])
        self.assertEqual(refusal(lambda: group(fx.jpeg(dto='2026:03:01 12:00:00', sub=None), 'captured', '0.5', subSecond='refuse')), 'TIME_SUBSECOND_REQUIRED')
        iptc_only = fx.jpeg(exif=False, xmp=None, iptc=[(2, 55, '20260301'), (2, 60, '120000+0100')])
        self.assertEqual(refusal(lambda: group(iptc_only, 'captured', '0.5')), 'TIME_SUBSECOND_REQUIRED')          # IPTC cannot hold a fraction
        self.assertEqual(group(iptc_only, 'captured', '60')['losses'], [])        # a whole-second shift loses nothing

    def test_T4_set_offset_keeps_the_instant(self):
        plan = group(fx.full_time(dto='2026:03:01 10:00:00', xmp=fx.xmp_properties(captured='2026-03-01T10:00:00.12+01:00'), iptc=[(2, 55, '20260301'), (2, 60, '100000+0100')]),
                     'captured', '0', {'minutes': 540, 'keep': 'instant'})
        # +01:00 -> +09:00 keeping the instant moves the wall clock by +8 hours: 18:00:00 +09:00
        self.assertEqual(plan['after'], {'local': '2026-03-01T18:00:00', 'offset': '+09:00', 'fraction': '12'})
        self.assertEqual(writes(plan), [('ExifIFD:DateTimeOriginal', '2026:03:01 18:00:00'), ('ExifIFD:OffsetTimeOriginal', '+09:00'),
                                        ('XMP-photoshop:DateCreated', '2026-03-01T18:00:00.12+09:00'), ('IPTC:TimeCreated', '180000+0900')])

    def test_T5_set_offset_keeping_the_wall_clock_changes_only_the_label(self):
        plan = group(fx.full_time(dto='2026:03:01 10:00:00', xmp=fx.xmp_properties(captured='2026-03-01T10:00:00.12+01:00'), iptc=[(2, 55, '20260301'), (2, 60, '100000+0100')]),
                     'captured', '0', {'minutes': 540, 'keep': 'wallClock'})
        self.assertEqual(plan['after'], {'local': '2026-03-01T10:00:00', 'offset': '+09:00', 'fraction': '12'})
        self.assertEqual(writes(plan), [('ExifIFD:OffsetTimeOriginal', '+09:00'), ('XMP-photoshop:DateCreated', '2026-03-01T10:00:00.12+09:00'), ('IPTC:TimeCreated', '100000+0900')])

    def test_keeping_the_instant_needs_a_recorded_or_assumed_offset(self):
        data = fx.jpeg(dto='2026:03:01 10:00:00', off=None, sub=None)
        self.assertEqual(refusal(lambda: group(data, 'captured', '0', {'minutes': 540, 'keep': 'instant'})), 'OFFSET_UNKNOWN')
        plan = group(data, 'captured', '0', {'minutes': 540, 'keep': 'instant'}, assumed=60)
        self.assertEqual((plan['after']['local'], plan['after']['offset']), ('2026-03-01T18:00:00', '+09:00'))
        # the offset carrier is created in the existing ExifIFD because the author set an offset
        self.assertEqual(writes(plan), [('ExifIFD:DateTimeOriginal', '2026:03:01 18:00:00'), ('ExifIFD:OffsetTimeOriginal', '+09:00')])

    def test_T12_conflicting_sources_are_refused_unless_a_family_is_preferred(self):
        data = fx.jpeg(dto='2026:03:01 12:00:00', sub=None, xmp=fx.xmp_properties(captured='2026-03-01T12:00:05+01:00'))
        self.assertEqual(refusal(lambda: group(data, 'captured', '60')), 'TIME_SOURCES_CONFLICT')
        plan = group(data, 'captured', '60', sourceConflicts='preferFamily', preferFamily='exif')
        # both sources are rewritten from the EXIF value; the XMP value the author chose not to prefer stays visible as the "before" of its target
        self.assertEqual(writes(plan), [('ExifIFD:DateTimeOriginal', '2026:03:01 12:01:00'), ('XMP-photoshop:DateCreated', '2026-03-01T12:01:00+01:00')])
        xmp_target = next(t for t in plan['targets'] if t['family'] == 'xmp')
        self.assertEqual(xmp_target['components'][0]['before'], '2026-03-01T12:00:05')
        # preferring a family that holds no value is itself a conflict the author must resolve
        both = fx.jpeg(exif=False, xmp=fx.xmp_properties(captured='2026-03-01T12:00:05+01:00', exif_dto='2026-03-01T12:00:09+01:00'))
        self.assertEqual(refusal(lambda: group(both, 'captured', '60', sourceConflicts='preferFamily', preferFamily='exif')), 'TIME_SOURCES_CONFLICT')

    def test_T13_an_unreadable_or_unsupported_source_is_never_overwritten(self):
        reduced = fx.jpeg(dto='2026:03:01 12:00:00', sub=None, xmp=fx.xmp_properties(captured='2026-03-01T12:00'))
        self.assertEqual(refusal(lambda: group(reduced, 'captured', '60')), 'TIME_SOURCE_UNREADABLE')
        self.assertEqual(refusal(lambda: group(fx.jpeg(dto='2016:12:31 23:59:60', sub=None), 'captured', '1')), 'TIME_SOURCE_UNREADABLE')     # second 60 is refused, not carried
        self.assertEqual(refusal(lambda: group(fx.jpeg(dto='2026:03:01 12:00:00', off='+15:00', sub=None), 'captured', '1')), 'TIME_SOURCE_UNREADABLE')

    def test_T15_results_outside_1900_to_2100_are_refused_per_item(self):
        self.assertEqual(refusal(lambda: group(fx.jpeg(dto='2100:12:31 23:59:59', sub=None), 'captured', '1')), 'TIME_OUT_OF_RANGE')
        self.assertEqual(refusal(lambda: group(fx.jpeg(dto='1900:01:01 00:00:00', sub=None), 'captured', '-1')), 'TIME_OUT_OF_RANGE')
        self.assertEqual(group(fx.jpeg(dto='2100:12:31 23:59:58', sub=None), 'captured', '1')['after']['local'], '2100-12-31T23:59:59')

    def test_T16_the_modified_field_has_its_own_sources(self):
        data = fx.jpeg(modify='2026:03:01 12:00:09', off_modify='+01:00', sub_modify='99', xmp=fx.xmp_properties(modified='2026-03-01T12:00:09.99+01:00'))
        plan = group(data, 'modified', '10')
        self.assertEqual(writes(plan), [('IFD0:ModifyDate', '2026:03:01 12:00:19'), ('XMP-xmp:ModifyDate', '2026-03-01T12:00:19.99+01:00')])
        self.assertIsNone(group(data, 'digitized', '10'))        # no digitized source: nothing to do

    def test_a_group_with_no_present_source_is_left_alone(self):
        self.assertIsNone(group(fx.jpeg(dto=None, sub=None, off=None), 'captured', '10'))

    def test_a_repeated_source_is_a_conflict_not_a_value(self):
        from schemaxis.adaptors.exiftool import edits
        twice = fx.jpeg(dto='2026:03:01 12:00:00', sub=None, exif_extra=[fx.a.ascii_entry(0x9003, '2026:03:01 12:00:01')])
        self.assertEqual(refusal(lambda: group(twice, 'captured', '1')), 'TIME_SOURCES_CONFLICT')

    def test_T19_and_T20_companion_sources_are_rewritten_together(self):
        data = fx.jpeg(dto='2026:03:01 12:00:00', sub=None, xmp=fx.xmp_properties(captured='2026-03-01T12:00:00+01:00', exif_dto='2026-03-01T12:00:00+01:00'))
        self.assertEqual(writes(group(data, 'captured', '60')), [('ExifIFD:DateTimeOriginal', '2026:03:01 12:01:00'), ('XMP-photoshop:DateCreated', '2026-03-01T12:01:00+01:00'),
                                                                 ('XMP-exif:DateTimeOriginal', '2026-03-01T12:01:00+01:00')])
        iptc = fx.jpeg(exif=False, xmp=None, iptc=[(2, 62, '20260301'), (2, 63, '120001+0100')])
        self.assertEqual(writes(group(iptc, 'digitized', '60')), [('IPTC:DigitalCreationTime', '120101+0100')])

    def test_the_created_exif_ifd_guard_and_no_creation_of_absent_sources(self):
        # a file whose only EXIF time is IFD0:ModifyDate and that has NO ExifIFD: setting an offset must not create OffsetTime there (that would create an ExifIFD, and the
        # native writer fills a created ExifIFD with an ExifVersion); with an ExifIFD present the carrier is created inside it
        data = fx.jpeg(exif=True, exif_version=None, dto=None, off=None, sub=None, modify='2026:03:01 12:00:09')
        self.assertEqual(containers.locate(data)['exif'] and records.Payloads(containers.locate(data)).exif[1]['ifds'].get('ExifIFD'), None)
        plan = group(data, 'modified', '1', {'minutes': 60, 'keep': 'wallClock'})
        self.assertEqual(writes(plan), [('IFD0:ModifyDate', '2026:03:01 12:00:10')])
        self.assertFalse(any(t['family'] == 'exif' and t['location'].startswith('ExifIFD') for t in plan['targets']))
        with_ifd = fx.jpeg(exif=True, exif_version=b'0300', dto=None, off=None, sub=None, modify='2026:03:01 12:00:09')
        self.assertEqual(writes(group(with_ifd, 'modified', '1', {'minutes': 60, 'keep': 'wallClock'})), [('IFD0:ModifyDate', '2026:03:01 12:00:10'), ('ExifIFD:OffsetTime', '+01:00')])


class Native(unittest.TestCase):
    """Real ExifTool 13.55: genuine writes, outputs read back by the standard-library walkers, truthful partial outcomes, plan-only runs and exact mutants."""

    @classmethod
    def setUpClass(cls):
        path = os.environ.get('SCHEMAXIS_EXIFTOOL')
        if not path or not os.path.isabs(path) or not Path(path).is_file() or not Path(adaptor.PERL).is_file():
            raise unittest.SkipTest('real ExifTool 13.55 is not configured through SCHEMAXIS_EXIFTOOL')
        cls.exe = path

    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix='e3-correct-'))
        self.addCleanup(shutil.rmtree, self.root, True)
        self.runs = 0

    def put(self, name, data):
        (self.root / (name + '.jpg')).write_bytes(data)

    def run_op(self, document):
        self.runs += 1
        out = self.root / ('run%d' % self.runs)
        result = adaptor.run(document, out, executable=self.exe)
        self.assertTrue(result['verified'])
        self.assertTrue(adaptor.verify(out, executable=self.exe)['verified'])
        return out

    def photo(self, out, name):
        return (out / 'photos' / (name + '.jpg')).read_bytes()

    def report(self, out, name='write-report.json'):
        return json.loads((out / name).read_text())

    def row(self, out, item):
        return next(r for r in self.report(out)['items'] if r['id'] == item)

    def outcome(self, out, item):
        return json.loads((out / 'outcomes' / (item + '.json')).read_text())

    # ---------------------------------------------------------------- values
    def test_T1_a_reference_correction_rewrites_exif_xmp_and_iptc_exactly(self):
        original = fx.full_time()
        self.put('a1', original)
        out = self.run_op(doc('correctTime', items(self.root, ['a1']), references=[{'item': 'a1', 'trueLocal': '2026-03-01T12:05:30.5', 'trueOffset': '+01:00'}],
                              corrections=[{'group': 'dev1', 'from': 'references'}]))
        data = self.photo(out, 'a1')
        self.assertEqual((fx.exif_ascii(data, 'ExifIFD', 0x9003), fx.exif_ascii(data, 'ExifIFD', 0x9291), fx.exif_ascii(data, 'ExifIFD', 0x9011)), ('2026:03:01 12:05:30', '50', '+01:00'))
        self.assertEqual(fx.xmp_value(data, 'photoshop:DateCreated'), '2026-03-01T12:05:30.50+01:00')
        self.assertEqual((fx.iim_value(data, 2, 55), fx.iim_value(data, 2, 60)), ('20260301', '120530+0100'))
        self.assertEqual(fx.exif_ascii(data, 'IFD0', 0x010F), 'A')                      # nothing else moved
        row = self.row(out, 'a1')
        self.assertEqual((row['status'], row['outcome']), ('written', 'corrected'))
        self.assertEqual([l['reason'] for l in row['losses']], ['iptcFractionDropped'])
        plan = self.report(out, 'time-correction-plan.json')['items'][0]
        self.assertEqual((plan['status'], plan['skewSeconds'], plan['basis']), ('planned', '-330.38', 'references'))
        self.assertEqual((self.root / 'a1.jpg').read_bytes(), original)                 # the original is never written

    def test_T2_and_T3_calendar_carries(self):
        self.put('leap', fx.jpeg(make='A', dto='2024:02:28 23:59:59', sub=None))
        self.put('year', fx.jpeg(make='B', dto='2023:12:31 23:59:59', sub='9'))
        self.put('feb', fx.jpeg(make='C', dto='2023:02:28 12:00:00', sub=None))
        out = self.run_op(doc('correctTime', items(self.root, ['leap', 'year', 'feb']),
                              corrections=[{'group': 'dev1', 'shift': {'seconds': '1'}}, {'group': 'dev2', 'shift': {'seconds': '0.2'}}, {'group': 'dev3', 'shift': {'days': 1}}]))
        self.assertEqual(fx.exif_ascii(self.photo(out, 'leap'), 'ExifIFD', 0x9003), '2024:02:29 00:00:00')
        year = self.photo(out, 'year')
        self.assertEqual((fx.exif_ascii(year, 'ExifIFD', 0x9003), fx.exif_ascii(year, 'ExifIFD', 0x9291)), ('2024:01:01 00:00:00', '1'))
        self.assertEqual(fx.exif_ascii(self.photo(out, 'feb'), 'ExifIFD', 0x9003), '2023:03:01 12:00:00')

    def utc(self, data):
        return fields_of(data)[0]['capturedUtcE3']['canonical']

    def test_T4_and_T5_set_offset_keeping_the_instant_or_the_wall_clock(self):
        make = lambda: fx.full_time(dto='2026:03:01 10:00:00', xmp=fx.xmp_properties(captured='2026-03-01T10:00:00.12+01:00'), iptc=[(2, 55, '20260301'), (2, 60, '100000+0100')])
        self.put('inst', make())
        self.put('wall', make())
        for name, keep in (('inst', 'instant'), ('wall', 'wallClock')):
            out = self.run_op(doc('correctTime', items(self.root, [name]), corrections=[{'group': 'dev1', 'setOffset': {'offset': '+09:00', 'keep': keep}}]))
            data = self.photo(out, name)
            expected_wall = '18:00:00' if keep == 'instant' else '10:00:00'
            self.assertEqual((fx.exif_ascii(data, 'ExifIFD', 0x9003), fx.exif_ascii(data, 'ExifIFD', 0x9011)), ('2026:03:01 ' + expected_wall, '+09:00'), keep)
            self.assertEqual(fx.xmp_value(data, 'photoshop:DateCreated'), '2026-03-01T%s.12+09:00' % expected_wall, keep)
            self.assertEqual((fx.iim_value(data, 2, 55), fx.iim_value(data, 2, 60)), ('20260301', expected_wall.replace(':', '') + '+0900'), keep)
            self.assertEqual(self.utc(data), '2026-03-01T09:00:00Z' if keep == 'instant' else '2026-03-01T01:00:00Z', keep)

    def test_T6_two_devices_one_reference_and_one_simultaneity_correct_both(self):
        # A is 5 s behind; b3 reads 30 s more than the simultaneous a5, so B is 25 s ahead
        for name, make, local in (('a1', 'A', '12:00:00'), ('a5', 'A', '12:10:00'), ('b3', 'B', '12:10:30'), ('b9', 'B', '15:00:25')):
            self.put(name, fx.jpeg(make=make, dto='2026:03:01 ' + local, sub=None))
        out = self.run_op(doc('correctTime', items(self.root, ['a1', 'a5', 'b3', 'b9']), references=[{'item': 'a1', 'trueLocal': '2026-03-01T12:00:05', 'trueOffset': '+01:00'}],
                              simultaneous=[{'items': ['a5', 'b3']}], corrections=[{'group': 'dev1', 'from': 'references'}, {'group': 'dev2', 'from': 'references'}]))
        got = {n: fx.exif_ascii(self.photo(out, n), 'ExifIFD', 0x9003) for n in ('a1', 'a5', 'b3', 'b9')}
        self.assertEqual(got, {'a1': '2026:03:01 12:00:05', 'a5': '2026:03:01 12:10:05', 'b3': '2026:03:01 12:10:05', 'b9': '2026:03:01 15:00:00'})
        self.assertEqual({g['id']: (g['state'], g['skewSeconds'], g['anchoredBy']) for g in self.report(out, 'time-report.json')['report']['groups']},
                         {'dev1': ('anchored', '-5', 'references'), 'dev2': ('anchored', '25', 'path')})

    def test_T9_linear_drift_corrects_inside_the_span_and_refuses_outside_it(self):
        # skew 0 at r0 and 8.64 s one day later: rate 1e-4; mid-span 4.32 s -> 11:59:55.68; r1 recorded 00:00:00 the next day is 8.64 s fast -> 23:59:51.36
        for name, local in (('r0', '2026:03:01 00:00:00'), ('mid', '2026:03:01 12:00:00'), ('r1', '2026:03:02 00:00:00'), ('late', '2026:03:02 00:00:10')):
            self.put(name, fx.jpeg(dto=local, sub=None))
        out = self.run_op(doc('correctTime', items(self.root, ['r0', 'mid', 'r1', 'late']), model='linearDrift', corrections=[{'group': 'dev1', 'from': 'references'}],
                              references=[{'item': 'r0', 'trueLocal': '2026-03-01T00:00:00', 'trueOffset': '+01:00'}, {'item': 'r1', 'trueLocal': '2026-03-01T23:59:51.36', 'trueOffset': '+01:00'}]))
        mid, r1 = self.photo(out, 'mid'), self.photo(out, 'r1')
        self.assertEqual((fx.exif_ascii(mid, 'ExifIFD', 0x9003), fx.exif_ascii(mid, 'ExifIFD', 0x9291)), ('2026:03:01 11:59:55', '68'))
        self.assertEqual((fx.exif_ascii(r1, 'ExifIFD', 0x9003), fx.exif_ascii(r1, 'ExifIFD', 0x9291)), ('2026:03:01 23:59:51', '36'))
        self.assertEqual(self.row(out, 'r0')['outcome'], 'unchanged')
        self.assertEqual((self.outcome(out, 'late')['fault']['code'], 'photos/late.jpg' in [str(p.relative_to(out)) for p in out.rglob('*.jpg')]), ('outsideReferenceSpan', False))

    # ---------------------------------------------------------------- truthful partial outcomes and stable slots
    def test_a_mixed_run_keeps_slots_stable_corrected_refused_unchanged(self):
        self.put('good', fx.full_time(make='A'))
        self.put('bad', fx.jpeg(make='B', dto='2026:03:01 12:00:00', sub=None, exif_extra=[fx.a.ascii_entry(0x9003, '2026:03:01 12:00:01')]))
        original_idle = fx.jpeg(make='C', dto='2026:03:01 12:00:00', sub=None)
        self.put('idle', original_idle)
        out = self.run_op(doc('correctTime', items(self.root, ['good', 'bad', 'idle']), corrections=[{'group': 'dev1', 'shift': {'seconds': '60'}}, {'group': 'dev2', 'shift': {'seconds': '60'}}]))
        artifacts = json.loads((out / 'verification.json').read_text())['artifacts']
        self.assertEqual([(a['kind'], (a.get('identity') or {}).get('item'), a.get('outcome')) for a in artifacts[:3]],
                         [('image', 'good', 'corrected'), ('text', 'bad', None), ('image', 'idle', 'unchanged')])
        self.assertEqual([Path(a['file']).name for a in artifacts[3:]], ['time-correction-plan.json', 'time-report.json', 'write-report.json', 'residual.json', 'manifest.json'])
        self.assertEqual(self.outcome(out, 'bad')['fault']['code'], 'TIME_SOURCES_CONFLICT')
        self.assertEqual((out / 'photos' / 'idle.jpg').read_bytes(), original_idle)                     # an unchanged item is a byte-identical copy
        manifest = self.report(out, 'manifest.json')
        self.assertEqual((manifest['status'], manifest['writeCounts']), ('partial', {'items': 3, 'written': 2, 'refused': 1, 'failed': 0}))

    def test_every_item_refused_fails_the_run_with_no_success_publication(self):
        for name, extra in (('a1', '12:00:00'), ('a2', '12:30:00')):
            self.put(name, fx.jpeg(dto='2026:03:01 ' + extra, sub=None))
        document = doc('correctTime', items(self.root, ['a1', 'a2']), corrections=[{'group': 'dev1', 'from': 'references'}],
                       references=[{'item': 'a1', 'trueLocal': '2026-03-01T12:00:00', 'trueOffset': '+01:00'}, {'item': 'a2', 'trueLocal': '2026-03-01T12:00:00', 'trueOffset': '+01:00'}])
        out = self.root / 'failed'
        with self.assertRaises(SchemaxisError) as caught:
            adaptor.run(document, out, executable=self.exe)
        self.assertEqual(caught.exception.fault.code, 'NO_USABLE_ITEMS')
        self.assertEqual(json.loads((out / 'result.json').read_text())['status'], 'failed')
        self.assertEqual(self.outcome(out, 'a1')['fault']['code'], 'GROUP_CONFLICTING')       # skews 0 and 1800 s: the references disagree, nothing is averaged away
        self.assertFalse((out / 'photos').exists())

    def test_T12_T13_T15_per_item_refusals_leave_the_other_items_written(self):
        self.put('ok', fx.jpeg(make='A', dto='2026:03:01 12:00:00', sub=None))
        self.put('conflict', fx.jpeg(make='B', dto='2026:03:01 12:00:00', sub=None, xmp=fx.xmp_properties(captured='2026-03-01T12:00:05+01:00')))
        self.put('reduced', fx.jpeg(make='C', dto='2026:03:01 12:00:00', sub=None, xmp=fx.xmp_properties(captured='2026-03-01T12:00')))
        self.put('late', fx.jpeg(make='D', dto='2100:12:31 23:59:59', sub=None))
        shift = lambda g: {'group': g, 'shift': {'seconds': '1'}}
        out = self.run_op(doc('correctTime', items(self.root, ['ok', 'conflict', 'reduced', 'late']), corrections=[shift('dev1'), shift('dev2'), shift('dev3'), shift('dev4')]))
        self.assertEqual([self.outcome(out, n)['fault']['code'] for n in ('conflict', 'reduced', 'late')], ['TIME_SOURCES_CONFLICT', 'TIME_SOURCE_UNREADABLE', 'TIME_OUT_OF_RANGE'])
        self.assertEqual(fx.exif_ascii(self.photo(out, 'ok'), 'ExifIFD', 0x9003), '2026:03:01 12:00:01')
        preferred = self.run_op(doc('correctTime', items(self.root, ['ok', 'conflict']), corrections=[shift('dev1'), shift('dev2')], policies={'sourceConflicts': 'preferFamily', 'preferFamily': 'exif'}))
        data = self.photo(preferred, 'conflict')
        self.assertEqual((fx.exif_ascii(data, 'ExifIFD', 0x9003), fx.xmp_value(data, 'photoshop:DateCreated')), ('2026:03:01 12:00:01', '2026-03-01T12:00:01+01:00'))

    def test_T16_modified_is_shifted_only_on_request(self):
        data = fx.jpeg(modify='2026:03:01 12:00:09', off_modify='+01:00', sub_modify='99', xmp=fx.xmp_properties(modified='2026-03-01T12:00:09.99+01:00'))
        self.put('m', data)
        default = self.run_op(doc('correctTime', items(self.root, ['m']), corrections=[{'group': 'dev1', 'shift': {'seconds': '10'}}]))
        kept = self.photo(default, 'm')
        self.assertEqual((fx.exif_ascii(kept, 'IFD0', 0x0132), fx.xmp_value(kept, 'xmp:ModifyDate'), fx.exif_ascii(kept, 'ExifIFD', 0x9003)), ('2026:03:01 12:00:09', '2026-03-01T12:00:09.99+01:00', '2026:03:01 12:00:10'))
        chosen = self.run_op(doc('correctTime', items(self.root, ['m']), timeFields=['modified'], corrections=[{'group': 'dev1', 'shift': {'seconds': '10'}}]))
        moved = self.photo(chosen, 'm')
        self.assertEqual((fx.exif_ascii(moved, 'IFD0', 0x0132), fx.xmp_value(moved, 'xmp:ModifyDate'), fx.exif_ascii(moved, 'ExifIFD', 0x9003)), ('2026:03:01 12:00:19', '2026-03-01T12:00:19.99+01:00', '2026:03:01 12:00:00'))

    def test_T17_an_item_without_time_fields_is_copied_or_refused_by_policy(self):
        original = fx.jpeg(dto=None, off=None, sub=None, make='B')
        self.put('good', fx.jpeg(make='A', dto='2026:03:01 12:00:00', sub=None))
        self.put('none', original)
        shift = [{'group': 'dev1', 'shift': {'seconds': '1'}}, {'group': 'dev2', 'shift': {'seconds': '1'}}]
        copied = self.run_op(doc('correctTime', items(self.root, ['good', 'none']), corrections=shift))
        self.assertEqual(((copied / 'photos' / 'none.jpg').read_bytes(), self.row(copied, 'none')['reason']), (original, 'noTimeFieldPresent'))
        refused = self.run_op(doc('correctTime', items(self.root, ['good', 'none']), corrections=shift, policies={'uncorrectedItems': 'refuseSlot'}))
        self.assertEqual(self.outcome(refused, 'none')['fault']['code'], 'ITEM_UNCHANGED')
        self.assertFalse((refused / 'photos' / 'none.jpg').exists())

    def test_T19_and_T20_companion_xmp_and_iptc_digitized_sources(self):
        self.put('x', fx.jpeg(dto='2026:03:01 12:00:00', sub=None, xmp=fx.xmp_properties(captured='2026-03-01T12:00:00+01:00', exif_dto='2026-03-01T12:00:00+01:00')))
        self.put('d', fx.jpeg(exif=False, iptc=[(2, 62, '20260301'), (2, 63, '120001+0100')]))
        out = self.run_op(doc('correctTime', items(self.root, ['x', 'd']), corrections=[{'group': 'dev1', 'shift': {'seconds': '60'}}, {'group': 'dev2', 'shift': {'seconds': '60'}}]))
        data = self.photo(out, 'x')
        self.assertEqual((fx.xmp_value(data, 'photoshop:DateCreated'), fx.xmp_value(data, 'exif:DateTimeOriginal')), ('2026-03-01T12:01:00+01:00', '2026-03-01T12:01:00+01:00'))
        self.assertEqual(fx.iim_value(self.photo(out, 'd'), 2, 63), '120101+0100')


    def test_E3W2_and_P3_4_a_wall_only_item_is_refused_when_the_references_give_it_no_constant_wall_skew(self):
        """Drift: the intercept is never an item's skew. Constant with trueUtc references: an instant skew is not a wall skew. Both agree with the reconcileTime report."""
        for name, local, offset in (('r1', '10:00:10', '+00:00'), ('r2', '20:00:45', '+00:00'), ('o', '15:00:38', '+00:00'), ('w', '15:00:38', None)):
            self.put(name, fx.jpeg(make='A', dto='2026:03:01 ' + local, off=offset, sub=None))
        refs = [{'item': 'r1', 'trueUtc': '2026-03-01T10:00:00Z'}, {'item': 'r2', 'trueUtc': '2026-03-01T20:00:00Z'}]
        out = self.root / 'drift'
        drift = doc('correctTime', items(self.root, ['r1', 'r2', 'o', 'w']), references=refs, model='linearDrift', corrections=[{'group': 'dev1', 'from': 'references'}])
        adaptor.run(drift, out, executable=self.exe)
        self.assertEqual(self.outcome(out, 'w')['fault']['code'], 'OFFSET_UNKNOWN')                   # not the 10 s intercept: 15:00:28 is never written
        self.assertTrue((out / 'photos' / 'o.jpg').is_file())                                           # the item with an instant is corrected by its own skew
        self.assertNotEqual(fx.exif_ascii(self.photo(out, 'o'), 'ExifIFD', 0x9003), '2026:03:01 15:00:28')
        read = self.root / 'drift-read'
        adaptor.run(doc('reconcileTime', items(self.root, ['r1', 'r2', 'o', 'w']), references=refs, model='linearDrift'), read, executable=self.exe)
        row = next(r for r in json.loads((read / 'time-report.json').read_text())['report']['items'] if r['id'] == 'w')
        self.assertEqual((row['skewSeconds'], row['proposedLocal']), (None, None))                    # the analysis and the correction say the same thing
        constant = self.root / 'constant'
        adaptor.run(doc('correctTime', items(self.root, ['r1', 'w']), references=refs[:1], corrections=[{'group': 'dev1', 'from': 'references'}]), constant, executable=self.exe)
        self.assertEqual(self.outcome(constant, 'w')['fault']['code'], 'OFFSET_UNKNOWN')


    def test_P3_2_an_edited_plan_in_a_plan_only_run_fails_with_the_same_exact_code_as_in_a_write_run(self):
        self.put('a1', fx.full_time(make='A'))
        planned = self.root / 'plan-only'
        adaptor.run(doc('correctTime', items(self.root, ['a1']), apply='plan', corrections=[{'group': 'dev1', 'shift': {'seconds': '60'}}]), planned, executable=self.exe)
        self.assertTrue(adaptor.verify(planned, executable=self.exe)['verified'])
        path = planned / 'time-correction-plan.json'
        data = path.read_bytes()
        self.assertIn(b'"shiftSeconds": "60"', data)
        path.write_bytes(data.replace(b'"shiftSeconds": "60"', b'"shiftSeconds": "61"', 1))
        with self.assertRaises(SchemaxisError) as caught:
            adaptor.verify(planned, executable=self.exe)
        fault = caught.exception.fault
        cause = fault.observed.get('cause', {})
        self.assertEqual((cause.get('code', fault.code), cause.get('location', fault.location)), ('PLAN_INCONSISTENT', 'time-correction-plan.json'))


class PlanAndMutants(unittest.TestCase):
    """One real mixed run is kept; plan-only and plan-application behaviour is exercised on fresh runs, and every mutant edits a copy of the retained run."""

    @classmethod
    def setUpClass(cls):
        path = os.environ.get('SCHEMAXIS_EXIFTOOL')
        if not path or not os.path.isabs(path) or not Path(path).is_file() or not Path(adaptor.PERL).is_file():
            raise unittest.SkipTest('real ExifTool 13.55 is not configured through SCHEMAXIS_EXIFTOOL')
        cls.exe = path
        cls.tmp = Path(tempfile.mkdtemp(prefix='e3-correct-mutants-')).resolve()
        cls.addClassCleanup(shutil.rmtree, cls.tmp, ignore_errors=True)
        cls.media = cls.tmp / 'media'
        cls.media.mkdir()
        cls.files = {'good': fx.full_time(make='A', modify='2026:03:01 12:00:09', off_modify='+01:00'), 'bad': fx.jpeg(make='B', dto='2026:03:01 12:00:00', sub=None, exif_extra=[fx.a.ascii_entry(0x9003, '2026:03:01 12:00:01')]),
                     'idle': fx.jpeg(make='C', dto='2026:03:01 12:00:00', sub=None)}
        for name, data in cls.files.items():
            (cls.media / (name + '.jpg')).write_bytes(data)
        cls.shift = [{'group': 'dev1', 'shift': {'seconds': '60'}}, {'group': 'dev2', 'shift': {'seconds': '60'}}]
        cls.main = cls.tmp / 'main'
        adaptor.run(doc('correctTime', items(cls.media, ['good', 'bad', 'idle']), corrections=cls.shift), cls.main, executable=cls.exe)

    def mutate(self, name, change, refresh_first=False):
        target = self.tmp / ('mutant-' + name)
        shutil.copytree(self.main, target, symlinks=True)
        change(target)
        if refresh_first:
            from test_exiftool_write_complete import refresh
            refresh(target, self.main)          # metadata first: stage digests, receipt evidence and artifact records, publication metadata
        with self.assertRaises(SchemaxisError) as caught:
            adaptor.verify(target, executable=self.exe)
        fault = caught.exception.fault
        cause = fault.observed.get('cause', {})
        problems = [p['code'] for p in cause.get('observed', {}).get('problems', [])] if isinstance(cause.get('observed'), dict) else []
        return cause.get('code', fault.code), cause.get('location', fault.location), problems

    def tamper(self, relative, replace):
        def go(directory):
            path = directory / relative
            path.write_bytes(replace(path.read_bytes()))
        return go

    @staticmethod
    def nth(data, old, new, n):
        """``data`` with the ``n``-th (0-based) occurrence of ``old`` replaced."""
        at = -1
        for _ in range(n + 1):
            at = data.index(old, at + 1)
        return data[:at] + new + data[at + len(old):]

    def test_the_unmutated_run_verifies(self):
        self.assertTrue(adaptor.verify(self.main, executable=self.exe)['verified'])

    def test_M_T1_T2_T3_a_written_time_component_that_reads_back_wrong_names_its_exact_location(self):
        photo = 'photos/good.jpg'
        code, location, problems = self.mutate('T1', self.tamper(photo, lambda d: d.replace(b'2026:03:01 12:01:00', b'2026:03:01 12:01:01', 1)))
        self.assertEqual((code, location), ('READBACK_MISMATCH', '$.items[0].fields.capturedLocalE3.exif'))
        code, location, problems = self.mutate('T2', self.tamper(photo, lambda d: d.replace(b'2026-03-01T12:01:00.12+01:00', b'2026-03-01T12:01:01.12+01:00', 1)))
        self.assertEqual((code, location), ('READBACK_MISMATCH', '$.items[0].fields.capturedLocalE3.xmp'))
        self.assertIn('READBACK_NOT_CONCORDANT', problems)                                # EXIF and XMP now also disagree with each other
        # the ExifIFD value area holds OffsetTime (modified, 0x9010) first and OffsetTimeOriginal (0x9011) second
        code, location, _ = self.mutate('T3', self.tamper(photo, lambda d: self.nth(d, b'+01:00\x00', b'+02:00\x00', 1)))
        self.assertEqual((code, location), ('READBACK_MISMATCH', '$.items[0].fields.capturedOffsetE3.exif'))
        code, location, _ = self.mutate('T3b', self.tamper(photo, lambda d: self.nth(d, b'+01:00\x00', b'+02:00\x00', 0)))
        self.assertEqual((code, location), ('READBACK_MISMATCH', '$.items[0].fields.modifiedOffset.exif'))         # an untouched source is held to its before value too

    def test_M_T5_a_silent_change_of_an_untouched_time_source_is_unrequested(self):
        code, location, problems = self.mutate('T5', self.tamper('photos/good.jpg', lambda d: d.replace(b'2026:03:01 12:00:09', b'2026:03:01 12:00:19', 1)))
        self.assertEqual((code, location), ('READBACK_MISMATCH', '$.items[0].fields.modifiedLocal.exif'))       # the untouched modified source is also held to its before value
        self.assertIn('UNREQUESTED_METADATA_CHANGED', problems)

    def test_M_L6_and_M_Y_a_change_outside_the_targets_is_unrequested_metadata(self):
        code, location, _ = self.mutate('make', self.tamper('photos/good.jpg', lambda d: d.replace(b'A\x00', b'Z\x00', 1)))
        self.assertEqual((code, location), ('UNREQUESTED_METADATA_CHANGED', '$.items[0].exif'))

    def test_M_P1_a_changed_entropy_byte_is_an_image_data_change(self):
        def flip(data):
            start = data.index(b'\xff\xda')
            length = int.from_bytes(data[start + 2:start + 4], 'big')
            at = start + 2 + length
            while data[at] == 0xFF or data[at + 1] == 0xFF:
                at += 1
            return data[:at] + bytes([data[at] ^ 0x01]) + data[at + 1:]
        code, location, _ = self.mutate('P1', self.tamper('photos/good.jpg', flip))
        self.assertEqual((code, location), ('IMAGE_DATA_CHANGED', '$.items[0].image'))

    def test_M_T4_an_edited_plan_is_not_the_plan_its_own_inputs_produce(self):
        code, location, _ = self.mutate('T4', self.tamper('time-correction-plan.json', lambda d: d.replace(b'"shiftSeconds": "60"', b'"shiftSeconds": "61"', 1)), refresh_first=True)
        self.assertEqual((code, location), ('PLAN_INCONSISTENT', 'time-correction-plan.json'))

    def test_M_S1_and_M_S2_slot_corruption_has_exact_codes(self):
        def drop_refused(directory):
            receipt = json.loads((directory / 'verification.json').read_text())
            del receipt['artifacts'][1]                                   # the refused item's outcome slot vanishes: idle now sits at index 1
            (directory / 'verification.json').write_text(json.dumps(receipt))

        def refused_as_image(directory):
            receipt = json.loads((directory / 'verification.json').read_text())
            receipt['artifacts'][1].update(kind='image', identity={'kind': 'image', 'format': 'jpeg', 'item': 'bad'})
            (directory / 'verification.json').write_text(json.dumps(receipt))
        self.assertEqual(self.mutate('S1', drop_refused, refresh_first=True)[0], 'SLOT_SHIFTED')       # metadata first: only the slot identity can still be wrong
        self.assertEqual(self.mutate('S2', refused_as_image, refresh_first=True)[0], 'FALSE_SUCCESS')

    def test_a_swapped_or_edited_report_fails_verification(self):
        code, location, _ = self.mutate('report', self.tamper('time-report.json', lambda d: d.replace(b'"state": "insufficient"', b'"state": "conflicting"', 1)))
        self.assertEqual((code, location), ('VERIFICATION_FAILED', 'time-report.json'))

    # ---------------------------------------------------------------- plan-only runs and plan application
    def doc(self, **extra):
        return doc('correctTime', items(self.media, ['good', 'idle']), corrections=self.shift[:1] + [{'group': 'dev2', 'shift': {'seconds': '60'}}], **extra)

    def test_T18_a_plan_only_run_publishes_documents_only_and_the_plan_applies_later(self):
        planned = self.tmp / 'planned'
        result = adaptor.run(self.doc(apply='plan'), planned, executable=self.exe)
        self.assertEqual((result['apply'], result['written'], result['planned']), ('plan', 0, 2))
        receipt = json.loads((planned / 'verification.json').read_text())
        self.assertEqual([Path(a['file']).name for a in receipt['artifacts']], ['time-correction-plan.json', 'time-report.json', 'manifest.json'])   # the plan is index 0 and there are no slots
        self.assertFalse((planned / 'photos').exists())
        self.assertEqual(adaptor.verify(planned, executable=self.exe)['apply'], 'plan')
        direct = self.tmp / 'direct'
        adaptor.run(self.doc(), direct, executable=self.exe)
        applied = self.tmp / 'applied'
        result = adaptor.run(doc('correctTime', items(self.media, ['good', 'idle']), plan=str(planned / 'time-correction-plan.json')), applied, executable=self.exe)
        self.assertEqual(result['verified'], True)
        for name in ('good', 'idle'):
            self.assertEqual((applied / 'photos' / (name + '.jpg')).read_bytes(), (direct / 'photos' / (name + '.jpg')).read_bytes(), name)
        plan = json.loads((applied / 'time-correction-plan.json').read_text())
        self.assertEqual(plan['appliedPlanSha256'], json.loads((applied / 'captures.json').read_text())['inputs']['plan']['sha256'])
        self.assertEqual(adaptor.verify(applied, executable=self.exe)['verified'], True)

    def test_T18_an_edited_or_stale_or_unknown_plan_is_refused(self):
        planned = self.tmp / 'planned-edit'
        adaptor.run(self.doc(apply='plan'), planned, executable=self.exe)
        text = (planned / 'time-correction-plan.json').read_text()
        original = json.loads(text)
        edited = json.loads(text)
        edited['items'][0]['arguments'][1] = '-ExifIFD:DateTimeOriginal=2026:03:01 13:00:00'
        path = self.tmp / 'edited-plan.json'
        path.write_text(json.dumps(edited))
        out = self.tmp / 'run-edited'
        adaptor.run(doc('correctTime', items(self.media, ['good', 'idle']), plan=str(path)), out, executable=self.exe)
        self.assertEqual(json.loads((out / 'outcomes' / 'good.json').read_text())['fault']['code'], 'PLAN_INCONSISTENT')        # recomputed, never trusted
        self.assertTrue((out / 'photos' / 'idle.jpg').is_file())
        # a capture that is not the file the plan was made for
        changed = self.tmp / 'changed'
        shutil.copytree(self.media, changed)
        (changed / 'good.jpg').write_bytes(self.files['good'].replace(b'A\x00', b'Z\x00', 1))
        out = self.tmp / 'run-stale'
        adaptor.run(doc('correctTime', items(changed, ['good', 'idle']), plan=str(planned / 'time-correction-plan.json')), out, executable=self.exe)
        self.assertEqual(json.loads((out / 'outcomes' / 'good.json').read_text())['fault']['code'], 'PLAN_STALE')
        # a plan that names an identity this code does not know, or whose declared block does not follow from its inputs
        for key, change, code in (('catalogue', lambda d: d['catalogue'].update(sha256='0' * 64), 'PLAN_CATALOGUE_UNKNOWN'), ('declared', lambda d: d['inputs']['corrections'][0]['shift'].update(seconds='61'), 'PLAN_INCONSISTENT')):
            forged = copy.deepcopy(original)
            change(forged)
            path = self.tmp / ('forged-%s.json' % key)
            path.write_text(json.dumps(forged))
            with self.assertRaises(SchemaxisError) as caught:
                adaptor.run(doc('correctTime', items(self.media, ['good', 'idle']), plan=str(path)), self.tmp / ('run-forged-' + key), executable=self.exe)
            self.assertEqual(caught.exception.fault.code, code, key)
        with self.assertRaises(SchemaxisError) as caught:
            adaptor.run(doc('correctTime', items(self.media, ['good']), plan=str(planned / 'authored.json')), self.tmp / 'run-wrong-kind', executable=self.exe)
        self.assertEqual(caught.exception.fault.code, 'PLAN_INVALID')


if __name__ == '__main__':
    unittest.main()
