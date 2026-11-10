"""E4 copyMetadata and applySidecar: hand-literal host planning cases and native runs against ExifTool 13.55 (contract cases C-1..C-9, C-R1..C-R4, C-D1, C-A1, C-A2, mutants).

Every expected value is a hand-written literal; outputs are read back with the shipped independent readers only to compare with those literals.
"""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT / 'tests/unit')]

import exiftool_e4_fixtures as f  # noqa: E402
from exiftool_e4_fixtures import V, master, plain, snapshot  # noqa: E402
from schemaxis.adaptors.exiftool import adaptor, e4copy, e4model, edits  # noqa: E402
from schemaxis.core.faults import SchemaxisError  # noqa: E402

COPY = {'version': V, 'operation': 'copyMetadata'}


class Host(unittest.TestCase):
    def doc(self, **extra):
        return {**COPY, 'media': {'items': [{'id': 'a', 'path': '/tmp/a.jpg'}, {'id': 'b', 'path': '/tmp/b.jpg'}]}, 'source': {'item': 'a'}, 'transfer': {'groups': ['descriptive']}, **extra}

    def fault(self, document, code, location=None):
        with self.assertRaises(SchemaxisError) as raised:
            adaptor.plan(document)
        self.assertEqual(raised.exception.fault.code, code)
        if location:
            self.assertEqual(raised.exception.fault.location, location)

    def test_the_plan_echoes_every_policy_with_its_default_and_the_selected_fields_in_catalogue_order(self):
        p = adaptor.plan(self.doc(transfer={'groups': ['exposure'], 'fields': ['title']}))
        self.assertEqual(p['policies'], {'existing': 'refuseConflict', 'absent': 'leaveDestination', 'ambiguous': 'refuseItem', 'loss': {'iptc': 'ifPresent', 'otherLanguages': 'keep', 'exifEncoding': 'utf8', 'companionLoss': 'removeCompanion'}})
        self.assertEqual(p['transfer']['fields'], ['title', 'exposureTime', 'fNumber', 'isoSpeed', 'focalLength', 'focalLength35mm', 'exposureBias'])
        self.assertEqual(p['writes']['version'], 'schemaxis.exiftool.writes/2')

    def test_an_unknown_or_non_transferable_selection_is_refused_and_the_e3_groups_compose_with_the_others(self):
        self.fault(self.doc(transfer={'groups': ['descriptive'], 'fields': ['orientation']}), 'INVALID_ARGUMENT')
        for groups in (['captureTime'], ['location'], ['captureTime', 'camera'], ['location', 'camera'], ['captureTime', 'location'], ['descriptive', 'captureTime', 'location']):
            fields = adaptor.plan(self.doc(transfer={'groups': groups}))['transfer']['fields']
            self.assertTrue({'captureTime', 'location'} & set(fields) and len(set(groups) - {'camera'}) <= len(groups))
        self.assertEqual(adaptor.plan(self.doc(transfer={'groups': ['descriptive', 'captureTime', 'location']}))['transfer']['fields'], ['title', 'description', 'keywords', 'captureTime', 'location'])
        self.fault(self.doc(transfer={}), 'INVALID_TRANSFER_SELECTION', '$.transfer')

    def test_selection_reasons_for_the_closed_non_transferable_list(self):
        for field in ('orientation', 'imageWidth', 'imageHeight', 'software', 'modifiedLocal', 'digitizedLocal'):
            with self.assertRaises(e4model.SelectionError) as raised:
                e4model.selection({'fields': [field]})
            self.assertIn('not transferable', raised.exception.message)

    def test_no_native_tag_option_or_tagsfromfile_can_be_authored(self):
        self.fault(self.doc(exiftoolArguments=['-tagsFromFile', 'a.jpg']), 'UNKNOWN_ARGUMENT')
        self.fault(self.doc(tagsFromFile='a.jpg'), 'UNKNOWN_ARGUMENT')
        self.fault(self.doc(transfer={'fields': ['IFD0:Make']}), 'INVALID_ARGUMENT')

    def test_sources_are_checked_against_the_media_set(self):
        self.fault(self.doc(source={'item': 'zzz'}), 'UNKNOWN_ITEM', '$.source.item')
        self.fault(self.doc(source={'pairs': [{'from': 'a', 'to': 'b'}, {'from': 'a', 'to': 'b'}]}), 'INVALID_ARGUMENT', '$.source.pairs[1].to')
        self.fault(self.doc(source={'file': {'path': 'relative.jpg'}}), 'INVALID_PHOTO_SOURCE')

    def test_apply_sidecar_pairs_declared_with_items_and_adjacent_with_a_folder(self):
        base = {'version': V, 'operation': 'applySidecar', 'transfer': {'groups': ['descriptive']}}
        self.fault({**base, 'media': {'items': [{'id': 'a', 'path': '/tmp/a.jpg'}]}, 'source': {'sidecar': 'declared'}}, 'INVALID_SIDECAR_SOURCE')
        self.fault({**base, 'media': {'items': [{'id': 'a', 'path': '/tmp/a.jpg', 'sidecar': '/tmp/a.xmp'}]}, 'source': {'sidecar': 'adjacent'}}, 'INVALID_SIDECAR_SOURCE')
        self.assertTrue(adaptor.plan({**base, 'media': {'folder': {'path': '/tmp/in'}}, 'source': {'sidecar': 'adjacent'}}))

    def test_decisions_follow_the_policies_exactly(self):
        P = {'existing': 'refuseConflict', 'absent': 'leaveDestination', 'ambiguous': 'refuseItem'}
        present = lambda v: {'state': 'present', 'value': v}
        self.assertEqual(e4copy.decide('rating', present(4), {'state': 'absent'}, P), ('write', 'destinationAbsent'))
        self.assertEqual(e4copy.decide('rating', present(4), present(4), P), ('unchanged', 'equal'))
        self.assertEqual(e4copy.decide('rating', present(4), present(3), {**P, 'existing': 'replace'}), ('write', 'replaced'))
        self.assertEqual(e4copy.decide('rating', present(4), present(3), {**P, 'existing': 'keepDestination'}), ('keep', 'keepDestination'))
        with self.assertRaises(edits.Refusal) as raised:
            e4copy.decide('rating', present(4), present(3), P)
        self.assertEqual(raised.exception.code, 'TRANSFER_CONFLICT')
        self.assertEqual(e4copy.decide('rating', {'state': 'absent'}, present(3), {**P, 'absent': 'clearDestination'}), ('clear', 'sourceAbsentCleared'))
        self.assertEqual(e4copy.decide('rating', {'state': 'absent'}, present(3), P), ('unchanged', 'sourceAbsent'))
        for state in ('unreadable', 'unsupported'):
            with self.assertRaises(edits.Refusal) as raised:
                e4copy.decide('rating', {'state': state}, present(3), {**P, 'absent': 'clearDestination'})
            self.assertEqual(raised.exception.code, 'TRANSFER_SOURCE_UNREADABLE')
            self.assertEqual(e4copy.decide('rating', {'state': state}, present(3), {**P, 'ambiguous': 'skipField'})[0], 'skip')
        with self.assertRaises(edits.Refusal) as raised:
            e4copy.decide('rating', {'state': 'ambiguous'}, present(3), P)
        self.assertEqual(raised.exception.code, 'TRANSFER_SOURCE_AMBIGUOUS')

    def test_R4_a_rational_with_the_same_value_and_another_pair_is_a_conflict_not_equal(self):
        P = {'existing': 'refuseConflict', 'absent': 'leaveDestination', 'ambiguous': 'refuseItem'}
        with self.assertRaises(edits.Refusal) as raised:
            e4copy.decide('exposureTime', {'state': 'present', 'value': (10, 30)}, {'state': 'present', 'value': (1, 3)}, P)
        self.assertEqual((raised.exception.code, raised.exception.observed['rationalPairDiffers']), ('TRANSFER_CONFLICT', True))
        self.assertEqual(e4copy.decide('exposureTime', {'state': 'present', 'value': (10, 30)}, {'state': 'present', 'value': (10, 30)}, P)[0], 'unchanged')

    def test_unrepresentable_extras_values_are_named_before_any_native_process(self):
        spec = e4copy.table()
        P = {'loss': {'exifEncoding': 'utf8'}}
        for field, value, code in (('exposureTimeE4', (-1, 2), 'TRANSFER_VALUE_NOT_REPRESENTABLE'), ('exposureTimeE4', (1, 2 ** 32), 'TRANSFER_VALUE_NOT_REPRESENTABLE'), ('lensMakeE4', 'x' * 256, 'TRANSFER_VALUE_NOT_REPRESENTABLE'),
                                   ('lensMakeE4', ' x', 'TRANSFER_VALUE_NOT_REPRESENTABLE'), ('isoSpeedE4', 70000, 'TRANSFER_VALUE_NOT_REPRESENTABLE')):
            found = e4copy.extra_value_problem(field, spec[field], value, P, '$')
            self.assertEqual(found['code'], code, (field, value))
        self.assertIsNone(e4copy.extra_value_problem('exposureBiasE4', spec['exposureBiasE4'], (-2, 6), P, '$'))
        self.assertEqual(e4copy.extra_value_problem('lensMakeE4', spec['lensMakeE4'], 'Linse ä', {'loss': {'exifEncoding': 'ascii'}}, '$')['code'], 'TRANSFER_VALUE_NOT_REPRESENTABLE')


class Native(f.NativeCase):
    ALL = ['descriptive', 'rights', 'camera', 'exposure', 'deviceSerials', 'rating', 'place']

    def copy(self, name, destinations=('b',), source=None, groups=None, policies=None, extra=('a',)):
        for n in extra:
            if not (self.media / (n + '.jpg')).exists():
                self.put(n + '.jpg', master())
        doc = {**COPY, 'media': self.items(*extra, *destinations), 'source': source or {'item': 'a'}, 'transfer': {'groups': groups or self.ALL}}
        if policies:
            doc['policies'] = policies
        return doc

    def test_C1_a_rich_source_transfers_exact_text_languages_lists_and_rational_pairs(self):
        self.put('b.jpg', plain())
        result = self.run_op(self.copy('c1', policies={'existing': 'replace'}), 'c1')
        self.assertEqual((result['written'], result['refused'], result['setStatus']), (1, 1, 'partial'))
        s = snapshot(self.read('c1', 'photos/b.jpg'), groups=['descriptive', 'rights', 'rating', 'camera', 'exposure', 'deviceSerials'])
        self.assertEqual(s['title']['value'], {'text': 'Harbour', 'languages': [{'language': 'de-DE', 'text': 'Hafen'}]})
        self.assertEqual((s['keywords']['value'], s['creator']['value'], s['copyright']['value']), (['k1', 'k2'], ['Ann; Bob', 'Cy'], {'text': '(c) 2024 A', 'languages': []}))
        self.assertEqual((s['cameraMake']['value'], s['cameraModel']['value'], s['lensMake']['value'], s['lensModel']['value']), ('Canon', 'EOS 5D', 'LensCo', 'L50'))
        self.assertEqual([s[k]['value'] for k in ('exposureTime', 'fNumber', 'focalLength', 'exposureBias')], [(10, 30), (28, 10), (35, 2), (-2, 6)])
        self.assertEqual((s['isoSpeed']['value'], s['focalLength35mm']['value'], s['rating']['value']), (400, 52, 4))
        self.assertEqual((s['bodySerialNumber']['value'], s['lensSerialNumber']['value']), ('B123', 'L456'))
        self.assertEqual(self.json('c1', 'manifest.json')['entries'][0]['outcome'], 'refused')
        self.assertEqual(self.json('c1', 'outcomes/a.json')['fault']['code'], 'TRANSFER_SELF')
        self.assertEqual(self.verify('c1')['proofs'], ['readback', 'preservation', 'nativeDiff'])
        self.record('test_exiftool_e4_transfer.Native.C1', 'copyMetadata', 'supported', supported=True, outcome='succeeded', independentlyVerified=True)

    def test_C2_a_conflicting_destination_is_refused_with_both_values_and_publishes_no_image(self):
        self.put('b.jpg', f.fx.jpeg(make='M', model='X', xmp=f.fx.xmp_properties(extra=f.lang_alt('dc:title', 'Old'))))
        self.put('c.jpg', plain(seed=5))
        result = self.run_op(self.copy('c2', ('b', 'c'), groups=['descriptive']), 'c2')
        self.assertEqual(result['written'], 1)
        fault = self.json('c2', 'outcomes/b.json')['fault']
        self.assertEqual((fault['code'], fault['observed']['source']['text'], fault['observed']['destination']['text']), ('TRANSFER_CONFLICT', 'Harbour', 'Old'))
        self.assertFalse((self.tmp / 'c2' / 'photos' / 'b.jpg').exists())

    def test_C3_keep_destination_skips_the_field_and_writes_the_others(self):
        self.put('b.jpg', f.fx.jpeg(make='M', model='X', xmp=f.fx.xmp_properties(extra=f.lang_alt('dc:title', 'Old'))))
        result = self.run_op(self.copy('c3', groups=['descriptive'], policies={'existing': 'keepDestination'}), 'c3')
        self.assertEqual(result['written'], 1)
        s = snapshot(self.read('c3', 'photos/b.jpg'), groups=['descriptive'])
        self.assertEqual((s['title']['value']['text'], s['keywords']['value']), ('Old', ['k1', 'k2']))
        decisions = {d['field']: (d['action'], d['reason']) for d in self.json('c3', 'transfer-report.json')['items'][1]['decisions']}
        self.assertEqual(decisions['title'], ('keep', 'keepDestination'))

    def test_C4_an_absent_source_field_clears_every_destination_form_by_policy(self):
        self.put('a.jpg', plain(seed=1))
        self.put('b.jpg', f.fx.jpeg(make='M', model='X', ifd0_extra=[f.a.ascii_entry(0x010E, 'Old text')], xmp=f.fx.xmp_properties(extra=f.lang_alt('dc:description', 'Old text')),
                                    iptc=[(2, 120, b'Old text')]))
        result = self.run_op(self.copy('c4', groups=['descriptive'], policies={'absent': 'clearDestination'}), 'c4')
        self.assertEqual(result['written'], 1)
        s = snapshot(self.read('c4', 'photos/b.jpg'), groups=['descriptive'])
        self.assertEqual(s['description']['state'], 'absent')
        self.assertEqual([x['state'] for x in s['description']['sources']], ['absent', 'absent', 'absent'])

    def test_C5_an_ambiguous_source_refuses_the_item_or_skips_the_field_by_policy(self):
        src = f.fx.jpeg(make='A', model='M', ifd0_extra=[f.a.ascii_entry(0x010E, 'Exif text')], xmp=f.fx.xmp_properties(extra=f.lang_alt('dc:description', 'Xmp text') + f.bag('dc:subject', 'k')))
        self.put('a.jpg', src)
        self.put('b.jpg', plain())
        fault = self.refuses(self.copy('c5', groups=['descriptive']), 'c5', 'NO_USABLE_ITEMS')
        self.assertIn('TRANSFER_SOURCE_AMBIGUOUS', {x['code'] for x in fault.observed['firstFaults']})
        result = self.run_op(self.copy('c5b', groups=['descriptive'], policies={'ambiguous': 'skipField'}), 'c5b')
        self.assertEqual(result['written'], 1)
        s = snapshot(self.read('c5b', 'photos/b.jpg'), groups=['descriptive'])
        self.assertEqual((s['description']['state'], s['keywords']['value']), ('absent', ['k']))

    def test_C6_a_malformed_source_xmp_is_unreadable_not_absent(self):
        self.put('a.jpg', f.fx.jpeg(make='A', model='M', xmp=f.fx.xmp_properties(extra='<dc:title><rdf:Alt>')))
        self.put('b.jpg', plain())
        fault = self.refuses(self.copy('c6', groups=['descriptive']), 'c6', 'NO_USABLE_ITEMS')
        self.assertEqual(fault.observed['firstFaults'][1]['code'], 'TRANSFER_SOURCE_UNREADABLE')

    def test_CM1_an_nfd_title_with_a_trailing_space_is_carried_exactly_and_listed_identically_by_the_native_listing(self):
        title = 'e\u0301 '
        self.put('a.jpg', f.fx.jpeg(make='A', model='M', xmp=f.fx.xmp_properties(extra=f.lang_alt('dc:title', title)), iptc=[(2, 5, title.encode('utf-8'))]))
        self.put('b.jpg', f.fx.jpeg(make='B', model='X', iptc=[(2, 5, b'old')], seed=2))
        result = self.run_op(self.copy('cm1', groups=['descriptive'], policies={'existing': 'replace'}), 'cm1')
        self.assertEqual(result['written'], 1)
        out = self.read('cm1', 'photos/b.jpg')
        s = snapshot(out, groups=['descriptive'])['title']
        self.assertEqual((s['state'], s['value']['text']), ('present', title))
        self.assertEqual([(x['family'], x['value']) for x in s['sources']], [('iptc', title), ('xmp', title)])
        self.assertIn(title.encode('utf-8'), out)                                     # the exact bytes, never trimmed or normalised
        proof = [r for r in self.json('cm1', 'transfer-report.json')['items'] if r['id'] == 'b'][0]['proofs']['T']
        self.assertTrue({'XMP-dc:Title', 'IPTC:ObjectName'} <= set(proof['nativeKeysCompared']))      # T-native compared the source and output tokens at both keys

    def test_C7_a_source_that_is_also_a_destination_is_read_from_its_capture(self):
        self.put('a.jpg', master())
        self.put('b.jpg', f.fx.jpeg(make='B-make', model='B-model', xmp=f.fx.xmp_properties(extra=f.bag('dc:subject', 'from-b'))))
        self.put('c.jpg', f.fx.jpeg(make='C-make', model='X', seed=7))
        self.put('d.jpg', plain(seed=8))
        self.put('e.jpg', plain(seed=9))
        doc = {**COPY, 'media': self.items('a', 'b', 'c', 'd', 'e'), 'source': {'pairs': [{'from': 'a', 'to': 'b'}, {'from': 'c', 'to': 'd'}, {'from': 'b', 'to': 'e'}]},
               'transfer': {'fields': ['keywords', 'cameraMake']}, 'policies': {'existing': 'replace', 'ambiguous': 'skipField'}}
        result = self.run_op(doc, 'c7')
        self.assertEqual(result['written'], 3)
        e = snapshot(self.read('c7', 'photos/e.jpg'), fields=['keywords', 'cameraMake'])
        self.assertEqual((e['keywords']['value'], e['cameraMake']['value']), (['from-b'], 'B-make'))       # b's CAPTURE, not the output that received a's values
        b = snapshot(self.read('c7', 'photos/b.jpg'), fields=['keywords', 'cameraMake'])
        self.assertEqual((b['keywords']['value'], b['cameraMake']['value']), (['k1', 'k2'], 'Canon'))
        plan_row = {e['id']: e for e in self.json('c7', 'transfer-plan.json')['items']}['e']
        self.assertEqual(plan_row['source']['sha256'], self.json('c7', 'manifest.json')['entries'][1]['sha256'])
        self.assertEqual(self.json('c7', 'outcomes/a.json')['fault']['code'], 'TRANSFER_NOT_A_DESTINATION')

    def test_C8_a_destination_equal_to_its_source_is_transfer_self(self):
        self.put('a.jpg', master())
        fault = self.refuses({**COPY, 'media': self.items('a'), 'source': {'item': 'a'}, 'transfer': {'groups': ['descriptive']}}, 'c8', 'NO_USABLE_ITEMS')
        self.assertEqual(fault.observed['firstFaults'][0]['code'], 'TRANSFER_SELF')
        self.assertFalse((self.tmp / 'c8' / 'photos').exists())          # nothing was published

    def test_C9_when_every_field_is_equal_the_item_is_unchanged_and_no_native_write_process_runs(self):
        self.put('a.jpg', master())
        self.put('b.jpg', master(seed=2))
        self.put('c.jpg', plain(seed=3))
        result = self.run_op(self.copy('c9', ('b', 'c'), groups=['descriptive', 'camera', 'exposure'], policies={'existing': 'replace'}), 'c9')
        self.assertEqual(result['refused'], 2)
        self.assertEqual(result['written'], 1)
        fault = self.json('c9', 'outcomes/b.json')['fault']
        self.assertEqual((fault['code'], fault['observed']['reason']), ('ITEM_UNCHANGED', 'nothingToTransfer'))
        names = {p.name for p in (self.tmp / 'c9').iterdir()}
        self.assertNotIn('write-b-launcher.py', names)
        self.assertIn('write-c-launcher.py', names)

    def test_R4_the_same_value_with_another_numerator_and_denominator_is_a_conflict(self):
        self.put('a.jpg', f.fx.jpeg(make='A', model='M', exif_extra=[f.rational(0x829A, 10, 30)]))
        self.put('b.jpg', f.fx.jpeg(make='A', model='M', exif_extra=[f.rational(0x829A, 1, 3)]))
        fault = self.refuses(self.copy('r4', groups=['exposure']), 'r4', 'NO_USABLE_ITEMS')
        self.assertEqual(fault.observed['firstFaults'][1]['code'], 'TRANSFER_CONFLICT')
        self.assertTrue(fault.observed['firstFaults'][1]['observed']['rationalPairDiffers'])
        result = self.run_op(self.copy('r4b', groups=['exposure'], policies={'existing': 'replace'}), 'r4b')
        self.assertEqual(result['written'], 1)
        self.assertEqual(snapshot(self.read('r4b', 'photos/b.jpg'), groups=['exposure'])['exposureTime']['value'], (10, 30))

    def test_R2_a_zero_denominator_in_the_source_is_unreadable(self):
        self.put('a.jpg', f.fx.jpeg(make='A', model='M', exif_extra=[f.rational(0x829A, 1, 0)]))
        self.put('b.jpg', plain())
        fault = self.refuses(self.copy('r2', groups=['exposure']), 'r2', 'NO_USABLE_ITEMS')
        self.assertIn('TRANSFER_SOURCE_UNREADABLE', {x['code'] for x in fault.observed['firstFaults']})

    def test_D1_device_serials_are_untouched_when_only_the_camera_group_is_requested(self):
        self.put('b.jpg', f.fx.jpeg(make='M', model='X', serial='KEEP-ME'))
        result = self.run_op(self.copy('d1', groups=['camera'], policies={'existing': 'replace'}), 'd1')
        self.assertEqual(result['written'], 1)
        s = snapshot(self.read('d1', 'photos/b.jpg'), groups=['camera', 'deviceSerials'])
        self.assertEqual((s['cameraMake']['value'], s['bodySerialNumber']['value']), ('Canon', 'KEEP-ME'))

    def test_a_destination_without_an_exif_block_is_refused_not_created(self):
        self.put('b.jpg', f.fx.jpeg(exif=False))
        self.put('c.jpg', plain(seed=4))
        result = self.run_op(self.copy('noexif', ('b', 'c'), groups=['camera'], policies={'existing': 'replace'}), 'noexif')
        self.assertEqual(result['written'], 1)
        fault = self.json('noexif', 'outcomes/b.json')['fault']
        self.assertEqual(fault['code'], 'TRANSFER_WOULD_CREATE_EXIF')

    def test_the_gps_only_height_meaning_is_not_changed_by_a_transfer_that_would_create_an_exif_ifd(self):
        gps = {'version': (2, 4, 0, 0), 'lat': [(10, 1), (0, 1), (0, 1)], 'lon': [(20, 1), (0, 1), (0, 1)], 'alt': (12, 1), 'alt_ref': 0}
        self.put('b.jpg', f.fx.jpeg(make='A', model='M', gps=gps, exif_version=None, dto=None, off=None, sub=None, exif_extra=[]))
        result_fault = None
        try:
            self.run_op(self.copy('gps', groups=['exposure']), 'gps')
        except SchemaxisError as error:
            result_fault = error.fault
        # whichever way the destination is classified, no output may exist that changed the untouched height meaning
        if result_fault is None:
            data = self.read('gps', 'photos/b.jpg')
            from schemaxis.adaptors.exiftool import containers, e3read, records
            before = e3read.height(records.Payloads(containers.locate((self.media / 'b.jpg').read_bytes())))
            after = e3read.height(records.Payloads(containers.locate(data)))
            self.assertEqual((before['reference'], before['state']), (after['reference'], after['state']))
        else:
            self.assertEqual(result_fault.code, 'NO_USABLE_ITEMS')
            self.assertIn(result_fault.observed['firstFaults'][-1]['code'], ('TRANSFER_WOULD_CREATE_EXIF', 'ALTITUDE_MEANING_CHANGED'))

    def test_A1_a_declared_sidecar_applies_its_values_and_A2_an_item_without_one_keeps_its_slot(self):
        self.put('a.jpg', master())
        self.run_op({'version': V, 'operation': 'exportSidecar', 'media': self.items('a'), 'transfer': {'groups': ['descriptive', 'rights', 'camera', 'exposure', 'deviceSerials']}}, 'exp')
        sidecar = str(self.tmp / 'exp' / 'sidecars' / 'a.xmp')
        self.put('copy.xmp', (self.tmp / 'exp' / 'sidecars' / 'a.xmp').read_bytes())
        second = str(self.media / 'copy.xmp')
        self.put('b.jpg', plain())
        self.put('c.jpg', plain(seed=5))
        self.put('d.jpg', plain(seed=6))
        items = [{'id': 'b', 'path': str(self.media / 'b.jpg'), 'sidecar': sidecar}, {'id': 'c', 'path': str(self.media / 'c.jpg')}, {'id': 'd', 'path': str(self.media / 'd.jpg'), 'sidecar': second}]
        doc = {'version': V, 'operation': 'applySidecar', 'media': {'items': items}, 'source': {'sidecar': 'declared'}, 'transfer': {'groups': ['descriptive', 'rights', 'camera', 'exposure', 'deviceSerials']}, 'policies': {'existing': 'replace'}}
        result = self.run_op(doc, 'apply')
        self.assertEqual((result['written'], result['refused']), (2, 1))
        self.assertEqual(self.json('apply', 'outcomes/c.json')['fault']['code'], 'SIDECAR_ABSENT')
        slots = self.json('apply', 'verification.json')['artifacts']
        self.assertEqual([(s['kind'], s['identity']['item']) for s in slots[:3]], [('image', 'b'), ('text', 'c'), ('image', 'd')])
        s = snapshot(self.read('apply', 'photos/b.jpg'), groups=['descriptive', 'rights', 'camera', 'exposure', 'deviceSerials'])
        self.assertEqual(s['title']['value'], {'text': 'Harbour', 'languages': [{'language': 'de-DE', 'text': 'Hafen'}]})
        self.assertEqual([s[k]['value'] for k in ('exposureTime', 'fNumber', 'focalLength', 'exposureBias')], [(10, 30), (28, 10), (35, 2), (-2, 6)])
        self.assertEqual((s['bodySerialNumber']['value'], s['lensSerialNumber']['value'], s['isoSpeed']['value']), ('B123', 'L456', 400))
        self.assertEqual(self.read('apply', 'captured/b.sidecar.xmp'), (self.tmp / 'exp' / 'sidecars' / 'a.xmp').read_bytes())
        self.assertEqual(self.read('apply', 'captured/d.sidecar.xmp'), (self.media / 'copy.xmp').read_bytes())
        self.assertEqual(self.verify('apply')['nativeReplay'], 'fresh-replay-matched')
        self.record('test_exiftool_e4_transfer.Native.A1', 'applySidecar', 'supported', supported=True, outcome='succeeded', independentlyVerified=True)

    def test_A1_adjacent_sidecars_are_paired_by_the_media_folder(self):
        self.put('a.jpg', master())
        self.run_op({'version': V, 'operation': 'exportSidecar', 'media': self.items('a'), 'transfer': {'groups': ['descriptive']}}, 'exp')
        self.put('b.jpg', plain())
        self.put('b.xmp', (self.tmp / 'exp' / 'sidecars' / 'a.xmp').read_bytes())
        self.put('c.jpg', plain(seed=5))
        (self.media / 'a.jpg').unlink()
        doc = {'version': V, 'operation': 'applySidecar', 'media': {'folder': {'path': str(self.media)}}, 'source': {'sidecar': 'adjacent'}, 'transfer': {'groups': ['descriptive']}}
        result = self.run_op(doc, 'adj')
        self.assertEqual((result['written'], result['refused']), (1, 1))
        self.assertEqual(snapshot(self.read('adj', 'photos/b.jpg'), groups=['descriptive'])['keywords']['value'], ['k1', 'k2'])

    def test_the_source_file_may_be_an_xmp_sidecar_and_a_wrong_pin_is_refused_before_anything_is_written(self):
        self.put('a.jpg', master())
        self.run_op({'version': V, 'operation': 'exportSidecar', 'media': self.items('a'), 'transfer': {'groups': ['descriptive', 'camera']}}, 'exp')
        sidecar = self.tmp / 'exp' / 'sidecars' / 'a.xmp'
        self.put('b.jpg', plain())
        doc = {**COPY, 'media': self.items('b'), 'source': {'file': {'path': str(sidecar)}}, 'transfer': {'groups': ['descriptive', 'camera']}, 'policies': {'existing': 'replace'}}
        result = self.run_op(doc, 'xmpsource')
        self.assertEqual(result['written'], 1)
        s = snapshot(self.read('xmpsource', 'photos/b.jpg'), groups=['descriptive', 'camera'])
        self.assertEqual((s['title']['value']['text'], s['keywords']['value'], s['cameraMake']['value']), ('Harbour', ['k1', 'k2'], 'Canon'))
        self.assertEqual(self.read('xmpsource', 'inputs/source.xmp'), sidecar.read_bytes())
        pinned = {**doc, 'source': {'file': {'path': str(sidecar), 'sha256': '0' * 64}}}
        fault = self.refuses(pinned, 'pin', 'PHOTO_HASH_MISMATCH')
        self.assertEqual(fault.location, '$.source.file.sha256')
        self.assertFalse((self.tmp / 'pin' / 'photos').exists())

    def test_a_modified_option_or_source_changes_the_plan_hash_and_unchanged_inputs_reuse(self):
        a = adaptor.plan({**COPY, 'media': {'items': [{'id': 'a', 'path': '/tmp/a.jpg'}, {'id': 'b', 'path': '/tmp/b.jpg'}]}, 'source': {'item': 'a'}, 'transfer': {'groups': ['descriptive']}})
        b = adaptor.plan({**COPY, 'media': {'items': [{'id': 'a', 'path': '/tmp/a.jpg'}, {'id': 'b', 'path': '/tmp/b.jpg'}]}, 'source': {'item': 'a'}, 'transfer': {'groups': ['descriptive']}, 'policies': {'existing': 'replace'}})
        self.assertNotEqual(adaptor.plan_hash(a), adaptor.plan_hash(b))


class Location(f.NativeCase):
    """The location group of copyMetadata and applySidecar: delegated to the E3 location planner, writer and proofs (contract cases C-E3b and the transfer of S-7)."""
    GPS = {'version': (2, 4, 0, 0), 'lat': [(35, 1), (7, 1), (24, 1)], 'lat_ref': 'N', 'lon': [(139, 1), (45, 1), (36, 1)], 'lon_ref': 'E', 'alt': (52317, 1000), 'alt_ref': 0, 'datum': 'WGS-84'}

    def doc(self, **extra):
        return {**COPY, 'media': self.items('a', 'b'), 'source': {'item': 'a'}, 'transfer': {'groups': ['location']}, **extra}

    def test_C_E3_the_position_and_its_ellipsoidal_height_are_written_by_the_location_writer(self):
        from fractions import Fraction
        from schemaxis.adaptors.exiftool import containers, e3read, records
        self.put('a.jpg', f.fx.jpeg(make='A', model='M', exif_version=b'0300', gps=self.GPS))
        self.put('b.jpg', f.fx.jpeg(make='B', model='X', exif_version=b'0300', seed=2))
        result = self.run_op(self.doc(), 'loc')
        self.assertEqual((result['written'], result['refused']), (1, 1))
        data = self.read('loc', 'photos/b.jpg')
        (d, dd), (m, md), (s, sd) = f.fx.exif_rationals(data, 'GPS', 0x0002)
        lat = Fraction(d, dd) + Fraction(m, md) / 60 + Fraction(s, sd) / 3600
        self.assertLessEqual(abs(lat - (Fraction(35) + Fraction(7, 60) + Fraction(24, 3600))), Fraction(1, 10 ** 9))
        self.assertEqual((f.fx.exif_ascii(data, 'GPS', 0x0001), f.fx.exif_ascii(data, 'GPS', 0x0003)), ('N', 'E'))
        height = e3read.height(records.Payloads(containers.locate(data)))
        self.assertEqual((height['state'], height['reference'], height['meters']), ('present', 'ellipsoidal', '52.317'))
        row = {e['id']: e for e in self.json('loc', 'transfer-plan.json')['items']}['b']
        self.assertEqual((row['decisions'][0]['action'], row['decisions'][0]['reason'], row['quantisation']['latitude']['written']), ('write', 'destinationAbsent', '35.123333333'))
        self.assertEqual(self.verify('loc')['proofs'], ['readback', 'preservation', 'nativeDiff'])

    def test_C_E3b_an_ellipsoidal_height_into_a_legacy_edition_file_is_the_e3_refusal_unchanged(self):
        self.put('a.jpg', f.fx.jpeg(make='A', model='M', exif_version=b'0300', gps=self.GPS))
        self.put('b.jpg', f.fx.jpeg(make='B', model='X', exif_version=b'0232', seed=2))
        fault = self.refuses(self.doc(), 'loc2', 'NO_USABLE_ITEMS')
        self.assertEqual(fault.observed['firstFaults'][1]['code'], 'ALTITUDE_REFERENCE_NOT_EXPRESSIBLE')

    def test_a_different_destination_position_is_a_conflict_with_both_values_and_the_same_one_is_unchanged(self):
        self.put('a.jpg', f.fx.jpeg(make='A', model='M', exif_version=b'0300', gps=self.GPS))
        other = dict(self.GPS, lat=[(10, 1), (0, 1), (0, 1)])
        self.put('b.jpg', f.fx.jpeg(make='B', model='X', exif_version=b'0300', gps=other, seed=2))
        fault = self.refuses(self.doc(), 'loc3', 'NO_USABLE_ITEMS')
        first = fault.observed['firstFaults'][1]
        self.assertEqual((first['code'], first['observed']['source']['latitude']), ('TRANSFER_CONFLICT', '35.123333333'))
        self.put('b.jpg', f.fx.jpeg(make='B', model='X', exif_version=b'0300', gps=self.GPS, seed=2))
        fault = self.refuses(self.doc(), 'loc4', 'NO_USABLE_ITEMS')
        self.assertEqual((fault.observed['firstFaults'][1]['code'], fault.observed['firstFaults'][1]['observed']['reason']), ('ITEM_UNCHANGED', 'equal'))


class CaptureTime(f.NativeCase):
    """The captureTime group of copyMetadata and applySidecar: the source's local time, offset and fraction carried through the E3 time planner (contract C-E3a), with hand-literal outputs."""

    def source(self, **kw):
        base = dict(make='A', model='M', dto='2024:03:01 10:20:30', off='+09:00', sub='25', exif_version=b'0300')
        base.update(kw)
        return f.fx.jpeg(**base)

    def destination(self, **kw):
        base = dict(make='B', model='X', dto='2020:01:01 00:00:00', off='+00:00', sub='12', exif_version=b'0300', seed=2)
        base.update(kw)
        return f.fx.jpeg(**base)

    def doc(self, **extra):
        return {**COPY, 'media': self.items('a', 'b'), 'source': {'item': 'a'}, 'transfer': {'groups': ['captureTime']}, 'policies': {'existing': 'replace'}, **extra}

    def read_time(self, data):
        return (f.fx.exif_ascii(data, 'ExifIFD', 0x9003), f.fx.exif_ascii(data, 'ExifIFD', 0x9011), f.fx.exif_ascii(data, 'ExifIFD', 0x9291))

    def test_C_E3a_local_time_offset_and_fraction_are_carried_by_the_e3_time_writer(self):
        self.put('a.jpg', self.source())
        self.put('b.jpg', self.destination())
        result = self.run_op(self.doc(), 'ct')
        self.assertEqual((result['written'], result['refused']), (1, 1))
        self.assertEqual(self.read_time(self.read('ct', 'photos/b.jpg')), ('2024:03:01 10:20:30', '+09:00', '25'))
        self.assertEqual(self.read_time(self.read('ct', 'captured/a.jpg')), ('2024:03:01 10:20:30', '+09:00', '25'))
        row = {e['id']: e for e in self.json('ct', 'transfer-plan.json')['items']}['b']
        self.assertEqual((row['decisions'][0]['action'], row['decisions'][0]['reason']), ('write', 'replaced'))
        self.assertEqual(self.verify('ct')['proofs'], ['readback', 'preservation', 'nativeDiff'])
        self.record('test_exiftool_e4_transfer.CaptureTime.C_E3a', 'copyMetadata', 'control')

    def test_every_present_time_family_of_the_destination_moves_together_and_nothing_else_does(self):
        self.put('a.jpg', f.fx.full_time(make='A', dto='2024:03:01 10:20:30', off='+09:00', sub='25', xmp=f.fx.xmp_properties(captured='2024-03-01T10:20:30.25+09:00'), iptc=[(2, 55, '20240301'), (2, 60, '102030+0900')]))
        self.put('b.jpg', f.fx.full_time(make='B', seed=2))
        result = self.run_op(self.doc(), 'fam')
        self.assertEqual(result['written'], 1)
        data = self.read('fam', 'photos/b.jpg')
        self.assertEqual(self.read_time(data), ('2024:03:01 10:20:30', '+09:00', '25'))
        snap = f.snapshot(data, fields=['captureTime'])['captureTime']
        self.assertEqual((snap['state'], snap['value']), ('present', {'local': '2024-03-01T10:20:30', 'offset': '+09:00', 'sub': '25'}))
        self.assertEqual(f.snapshot(data, fields=['cameraMake'])['cameraMake']['value'], 'B')            # every other value is untouched

    def test_a_declared_sidecar_carries_its_time_into_the_copy(self):
        self.put('a.jpg', self.source())
        self.run_op({'version': V, 'operation': 'exportSidecar', 'media': self.items('a'), 'transfer': {'groups': ['captureTime']}}, 'exp')
        self.put('b.jpg', self.destination())
        doc = {'version': V, 'operation': 'applySidecar', 'media': {'items': [{'id': 'b', 'path': str(self.media / 'b.jpg'), 'sidecar': str(self.tmp / 'exp' / 'sidecars' / 'a.xmp')}]},
               'source': {'sidecar': 'declared'}, 'transfer': {'groups': ['captureTime']}, 'policies': {'existing': 'replace'}}
        result = self.run_op(doc, 'apply')
        self.assertEqual(result['written'], 1)
        self.assertEqual(self.read_time(self.read('apply', 'photos/b.jpg')), ('2024:03:01 10:20:30', '+09:00', '25'))
        self.assertEqual(self.verify('apply')['nativeReplay'], 'fresh-replay-matched')

    def test_a_destination_without_an_offset_receives_the_source_offset_keeping_the_wall_clock(self):
        self.put('a.jpg', self.source())
        self.put('b.jpg', self.destination(off=None))
        result = self.run_op(self.doc(), 'nooff')
        self.assertEqual(result['written'], 1)
        self.assertEqual(self.read_time(self.read('nooff', 'photos/b.jpg')), ('2024:03:01 10:20:30', '+09:00', '25'))

    def test_controls_equal_conflict_offset_precision(self):
        self.put('a.jpg', self.source())
        self.put('b.jpg', self.source(seed=2))
        fault = self.refuses(self.doc(), 'eq', 'NO_USABLE_ITEMS')
        self.assertEqual((fault.observed['firstFaults'][1]['code'], fault.observed['firstFaults'][1]['observed']['reason']), ('ITEM_UNCHANGED', 'equal'))
        self.put('b.jpg', self.destination())
        fault = self.refuses({**self.doc(), 'policies': {}}, 'conflict', 'NO_USABLE_ITEMS')
        first = fault.observed['firstFaults'][1]
        self.assertEqual((first['code'], first['observed']['source']['local'], first['observed']['destination']['local']), ('TRANSFER_CONFLICT', '2024-03-01T10:20:30', '2020-01-01T00:00:00'))
        self.put('a.jpg', self.source(off=None))
        fault = self.refuses(self.doc(), 'offset', 'NO_USABLE_ITEMS')
        self.assertEqual(fault.observed['firstFaults'][1]['code'], 'TRANSFER_TIME_OFFSET_CONFLICT')
        self.put('a.jpg', self.source())
        self.put('b.jpg', self.destination(sub='123456'))
        fault = self.refuses(self.doc(), 'precision', 'NO_USABLE_ITEMS')
        self.assertEqual((fault.observed['firstFaults'][1]['code'], fault.observed['firstFaults'][1]['observed']['written']), ('TRANSFER_TIME_FRACTION_PRECISION', '250000'))


class Mixed(f.NativeCase):
    """Mixed selections: E2 edits, the extras table and the E3 time and location plans composed into one native write with every part proved on the same output bytes (contract section 1: groups and fields are a union)."""
    GPS = Location.GPS

    def source(self, **kw):
        base = dict(make='Canon', model='EOS 5D', dto='2024:03:01 10:20:30', off='+09:00', sub='25', exif_version=b'0300', gps=self.GPS, serial='B123',
                    xmp=f.fx.xmp_properties(captured='2024-03-01T10:20:30.25+09:00', extra=f.lang_alt('dc:title', 'Harbour', de_DE='Hafen') + f.bag('dc:subject', 'k1', 'k2')),
                    exif_extra=[f.rational(0x829A, 10, 30), f.rational(0x829D, 28, 10)])
        base.update(kw)
        return f.fx.jpeg(**base)

    def destination(self, **kw):
        base = dict(make='Other', model='Old', dto='2020:01:01 00:00:00', off='+00:00', sub='12', exif_version=b'0300', seed=2, xmp=f.fx.xmp_properties(captured='2020-01-01T00:00:00.12+00:00'))
        base.update(kw)
        return f.fx.jpeg(**base)

    def doc(self, groups, **extra):
        return {**COPY, 'media': self.items('a', 'b'), 'source': {'item': 'a'}, 'transfer': {'groups': groups}, 'policies': {'existing': 'replace'}, **extra}

    def test_descriptive_capture_time_and_location_are_written_together_and_proved_together(self):
        from fractions import Fraction
        from schemaxis.adaptors.exiftool import containers, e3read, records
        self.put('a.jpg', self.source())
        self.put('b.jpg', self.destination())
        result = self.run_op(self.doc(['descriptive', 'captureTime', 'location']), 'mx')
        self.assertEqual((result['written'], result['refused']), (1, 1))
        data = self.read('mx', 'photos/b.jpg')
        s = snapshot(data, groups=['descriptive', 'captureTime'])
        self.assertEqual((s['title']['value'], s['keywords']['value']), ({'text': 'Harbour', 'languages': [{'language': 'de-DE', 'text': 'Hafen'}]}, ['k1', 'k2']))
        self.assertEqual((f.fx.exif_ascii(data, 'ExifIFD', 0x9003), f.fx.exif_ascii(data, 'ExifIFD', 0x9011), f.fx.exif_ascii(data, 'ExifIFD', 0x9291)), ('2024:03:01 10:20:30', '+09:00', '25'))
        self.assertEqual(s['captureTime']['value'], {'local': '2024-03-01T10:20:30', 'offset': '+09:00', 'sub': '25'})
        (d, dd), (m, md), (sec, sd) = f.fx.exif_rationals(data, 'GPS', 0x0002)
        self.assertLessEqual(abs(Fraction(d, dd) + Fraction(m, md) / 60 + Fraction(sec, sd) / 3600 - (Fraction(35) + Fraction(7, 60) + Fraction(24, 3600))), Fraction(1, 10 ** 9))
        height = e3read.height(records.Payloads(containers.locate(data)))
        self.assertEqual((height['reference'], height['meters']), ('ellipsoidal', '52.317'))
        self.assertEqual(f.snapshot(data, fields=['cameraMake'])['cameraMake']['value'], 'Other')                      # an unselected value is untouched
        report = [r for r in self.json('mx', 'transfer-report.json')['items'] if r['id'] == 'b'][0]
        self.assertEqual({d['field'] for d in report['decisions'] if d['action'] == 'write'}, {'title', 'keywords', 'captureTime', 'location'})
        self.assertEqual(self.verify('mx')['proofs'], ['readback', 'preservation', 'nativeDiff'])
        self.record('test_exiftool_e4_transfer.Mixed.mixed_all', 'copyMetadata', 'control')

    def test_camera_exposure_and_capture_time_compose_with_exact_pairs(self):
        self.put('a.jpg', self.source())
        self.put('b.jpg', self.destination())
        result = self.run_op(self.doc(['camera', 'exposure', 'captureTime']), 'mx2')
        self.assertEqual(result['written'], 1)
        data = self.read('mx2', 'photos/b.jpg')
        s = snapshot(data, groups=['camera', 'exposure'])
        self.assertEqual((s['cameraMake']['value'], s['exposureTime']['value'], s['fNumber']['value']), ('Canon', (10, 30), (28, 10)))
        self.assertEqual(f.fx.exif_ascii(data, 'ExifIFD', 0x9003), '2024:03:01 10:20:30')

    def test_a_declared_sidecar_composes_descriptive_and_capture_time(self):
        self.put('a.jpg', self.source())
        self.run_op({'version': V, 'operation': 'exportSidecar', 'media': self.items('a'), 'transfer': {'groups': ['descriptive', 'captureTime']}}, 'exp')
        self.put('b.jpg', self.destination())
        doc = {'version': V, 'operation': 'applySidecar', 'media': {'items': [{'id': 'b', 'path': str(self.media / 'b.jpg'), 'sidecar': str(self.tmp / 'exp' / 'sidecars' / 'a.xmp')}]},
               'source': {'sidecar': 'declared'}, 'transfer': {'groups': ['descriptive', 'captureTime']}, 'policies': {'existing': 'replace'}}
        self.assertEqual(self.run_op(doc, 'mxs')['written'], 1)
        data = self.read('mxs', 'photos/b.jpg')
        self.assertEqual((snapshot(data, groups=['descriptive'])['keywords']['value'], f.fx.exif_ascii(data, 'ExifIFD', 0x9291)), (['k1', 'k2'], '25'))

    def test_a_conflicting_selected_field_refuses_the_whole_item_and_nothing_is_written(self):
        self.put('a.jpg', self.source())
        self.put('b.jpg', self.destination(xmp=f.fx.xmp_properties(captured='2020-01-01T00:00:00.12+00:00', extra=f.lang_alt('dc:title', 'Old'))))
        fault = self.refuses({**self.doc(['descriptive', 'captureTime', 'location']), 'policies': {'existing': 'refuseConflict'}}, 'mxc', 'NO_USABLE_ITEMS')
        first = fault.observed['firstFaults'][1]
        self.assertEqual(first['code'], 'TRANSFER_CONFLICT')
        self.assertFalse((self.tmp / 'mxc' / 'photos').exists())

    def test_an_unrepresentable_selected_part_refuses_the_whole_item_with_its_precise_code(self):
        self.put('a.jpg', self.source(off=None, xmp=f.fx.xmp_properties(captured='2024-03-01T10:20:30.25', extra=f.lang_alt('dc:title', 'Harbour'))))
        self.put('b.jpg', self.destination())
        fault = self.refuses(self.doc(['descriptive', 'captureTime']), 'mxu', 'NO_USABLE_ITEMS')
        self.assertEqual(fault.observed['firstFaults'][1]['code'], 'TRANSFER_TIME_OFFSET_CONFLICT')
        self.assertFalse((self.tmp / 'mxu' / 'photos').exists())
        self.put('a.jpg', self.source())
        self.put('b.jpg', self.destination(exif_version=b'0232'))
        fault = self.refuses(self.doc(['descriptive', 'location']), 'mxe', 'NO_USABLE_ITEMS')
        self.assertEqual(fault.observed['firstFaults'][1]['code'], 'ALTITUDE_REFERENCE_NOT_EXPRESSIBLE')

    def test_M_a_changed_capture_time_in_a_mixed_output_is_a_transfer_readback_mismatch(self):
        self.put('a.jpg', self.source())
        self.put('b.jpg', self.destination())
        self.run_op(self.doc(['descriptive', 'captureTime', 'location']), 'mxm')

        def change(target):
            path = target / 'photos' / 'b.jpg'
            data = path.read_bytes()
            assert data.count(b'2024:03:01 10:20:30') >= 1
            path.write_bytes(data.replace(b'2024:03:01 10:20:30', b'2024:03:01 10:20:31', 1))
        f.mutate_and_refresh(self, 'mxm', 'mixed-time', change, 'TRANSFER_READBACK_MISMATCH')


class Mutants(f.NativeCase):
    def setUp(self):
        super().setUp()
        self.put('a.jpg', master())
        self.put('b.jpg', plain())
        doc = {**COPY, 'media': self.items('a', 'b'), 'source': {'item': 'a'}, 'transfer': {'groups': ['descriptive', 'exposure']}, 'policies': {'existing': 'replace'}}
        self.run_op(doc, 'base')

    def edit_output(self, old, new):
        def change(target):
            path = target / 'photos' / 'b.jpg'
            data = path.read_bytes()
            assert old in data, old
            path.write_bytes(data.replace(old, new, 1))
        return change

    def test_M_a_changed_title_after_publish_is_a_transfer_readback_mismatch(self):
        code, location = f.mutate_and_refresh(self, 'base', 'title', self.edit_output(b'Harbour', b'Harbouu'), 'TRANSFER_READBACK_MISMATCH')
        self.assertIn('items[1]', location)

    def test_M_a_rational_stored_as_one_third_for_the_requested_ten_thirtieths_is_a_transfer_readback_mismatch(self):
        raw = (self.tmp / 'base' / 'photos' / 'b.jpg').read_bytes()
        pair = (10).to_bytes(4, 'little') + (30).to_bytes(4, 'little')
        self.assertEqual(raw.count(pair), 1)
        f.mutate_and_refresh(self, 'base', 'pair', self.edit_output(pair, (1).to_bytes(4, 'little') + (3).to_bytes(4, 'little')), 'TRANSFER_READBACK_MISMATCH')

    def test_M_a_flipped_source_capture_byte_fails_verification_at_the_capture(self):
        def change(target):
            path = target / 'captured' / 'a.jpg'
            data = bytearray(path.read_bytes())
            data[-5] ^= 1
            path.write_bytes(bytes(data))
        code, location = f.mutate_and_refresh(self, 'base', 'capture', change, 'VERIFICATION_FAILED')
        self.assertIn('captured/a.jpg', location)

    def test_M_a_kept_field_that_changed_is_a_transfer_readback_mismatch(self):
        self.put('c.jpg', f.fx.jpeg(make='C-make', model='X', xmp=f.fx.xmp_properties(extra=f.lang_alt('dc:title', 'Old'))))
        doc = {**COPY, 'media': self.items('a', 'c'), 'source': {'item': 'a'}, 'transfer': {'groups': ['descriptive']}, 'policies': {'existing': 'keepDestination'}}
        self.run_op(doc, 'keep')

        def change(target):
            path = target / 'photos' / 'c.jpg'
            path.write_bytes(path.read_bytes().replace(b'>Old<', b'>New<', 1))
        f.mutate_and_refresh(self, 'keep', 'kept', change, 'TRANSFER_READBACK_MISMATCH')

    def test_M_CM1_an_nfc_and_stripped_title_in_the_output_is_a_transfer_readback_mismatch(self):
        title = 'e\u0301 '
        self.put('c.jpg', f.fx.jpeg(make='C', model='M', xmp=f.fx.xmp_properties(extra=f.lang_alt('dc:title', title)), seed=5))
        self.put('d.jpg', f.fx.jpeg(make='D', model='X', seed=6))
        self.run_op({**COPY, 'media': self.items('c', 'd'), 'source': {'item': 'c'}, 'transfer': {'groups': ['descriptive']}}, 'cm1base')
        mangled = 'e\u0301 '.encode('utf-8'), '\u00e9  '.encode('utf-8')           # the NFC form with the length kept: what a normalising reader would report

        def change(target):
            path = target / 'photos' / 'd.jpg'
            data = path.read_bytes()
            assert mangled[0] in data
            path.write_bytes(data.replace(mangled[0], mangled[1], 1))
        f.mutate_and_refresh(self, 'cm1base', 'cm1-nfc', change, 'TRANSFER_READBACK_MISMATCH')

    def test_M_an_xmp_property_the_plan_does_not_name_is_an_unexplained_native_change(self):
        injected = b'<tiff:Software xmlns:tiff="http://ns.adobe.com/tiff/1.0/">mutant</tiff:Software>'

        def change(target):
            path = target / 'photos' / 'b.jpg'
            data = path.read_bytes()
            end = data.index(b'</rdf:Description>')
            padding = data.index(b' ' * (len(injected) + 8), end)
            path.write_bytes(data[:end] + injected + data[end:padding] + data[padding + len(injected):])
        code, location = f.mutate_and_refresh(self, 'base', 'unexplained', change, 'NATIVE_UNEXPLAINED_CHANGE')
        self.assertIn('native', location)


class Repair(f.NativeCase):
    """The E4 repair cases (final review E4R1..E4R6), every expected value a hand-written literal: the captured time set into destinations that record none, exact language alternatives,
    the independent source-to-output proof T for single and mixed time and location, three-family destinations in mixed selections, a reader mutant isolated to T-native, and absent/absent."""
    GPS = Location.GPS
    TIME = {'local': '2024-03-01T10:20:30', 'offset': '+09:00', 'sub': '25'}

    def source(self, **kw):
        base = dict(make='A', model='M', dto='2024:03:01 10:20:30', off='+09:00', sub='25', exif_version=b'0300', xmp=f.fx.xmp_properties(extra=f.lang_alt('dc:title', 'Harbour')))
        base.update(kw)
        return f.fx.jpeg(**base)

    def timeless(self, **kw):
        base = dict(make='B', model='X', dto=None, off=None, sub=None, exif_version=b'0300', seed=2)
        base.update(kw)
        return f.fx.jpeg(**base)

    def doc(self, groups, **extra):
        return {**COPY, 'media': self.items('a', 'b'), 'source': {'item': 'a'}, 'transfer': {'groups': groups}, 'policies': {'existing': 'replace'}, **extra}

    def time_of(self, data):
        return (f.fx.exif_ascii(data, 'ExifIFD', 0x9003), f.fx.exif_ascii(data, 'ExifIFD', 0x9011), f.fx.exif_ascii(data, 'ExifIFD', 0x9291))

    def item(self, name, item_id='b'):
        return {e['id']: e for e in self.json(name, 'transfer-report.json')['items']}[item_id]

    def test_E4R1_a_captured_time_is_set_into_an_exififd_that_records_none(self):
        self.put('a.jpg', self.source())
        self.put('b.jpg', self.timeless())
        result = self.run_op(self.doc(['captureTime']), 'r1a')
        self.assertEqual((result['written'], result['refused']), (1, 1))
        self.assertEqual(self.time_of(self.read('r1a', 'photos/b.jpg')), ('2024:03:01 10:20:30', '+09:00', '25'))
        row = self.item('r1a')
        self.assertEqual((row['outcome'], row['decisions'][0]['action'], row['decisions'][0]['reason']), ('transferred', 'write', 'destinationAbsent'))
        self.assertEqual(sorted(row['proofs']), ['N', 'P', 'R', 'T', 'problems'])
        self.assertTrue(any(l.get('reason') == 'timeCreatedInExifOnly' for l in row['losses']))
        self.assertEqual(self.verify('r1a')['nativeReplay'], 'fresh-replay-matched')

    def test_E4R1_a_mixed_descriptive_and_time_selection_never_drops_the_time(self):
        self.put('a.jpg', self.source())
        self.put('b.jpg', self.timeless())
        result = self.run_op(self.doc(['descriptive', 'captureTime']), 'r1b')
        self.assertEqual(result['written'], 1)
        data = self.read('r1b', 'photos/b.jpg')
        self.assertEqual(self.time_of(data), ('2024:03:01 10:20:30', '+09:00', '25'))
        self.assertEqual(snapshot(data, fields=['title', 'captureTime'])['title']['value']['text'], 'Harbour')
        self.assertEqual([d['field'] for d in self.item('r1b')['decisions'] if d['action'] == 'write'], ['title', 'captureTime'])
        self.assertEqual(self.verify('r1b')['nativeReplay'], 'fresh-replay-matched')

    def test_E4R1_a_blank_destination_receives_the_time_in_xmp_and_no_exif_block_is_created(self):
        self.put('a.jpg', self.source())
        self.put('b.jpg', f.fx.jpeg(exif=False, xmp=None, seed=3))
        result = self.run_op(self.doc(['captureTime']), 'r1c')
        self.assertEqual(result['written'], 1)
        data = self.read('r1c', 'photos/b.jpg')
        self.assertEqual(snapshot(data, fields=['captureTime'])['captureTime']['value'], self.TIME)
        self.assertEqual(f.fx.exif_ascii(data, 'ExifIFD', 0x9003), None)
        self.assertIn(b'<exif:DateTimeOriginal>2024-03-01T10:20:30.25+09:00</exif:DateTimeOriginal>', data)
        self.assertTrue(any(l.get('reason') == 'timeCreatedInXmpOnly' for l in self.item('r1c')['losses']))
        self.assertEqual(self.verify('r1c')['nativeReplay'], 'fresh-replay-matched')

    def test_E4R1_a_mixed_selection_into_a_blank_destination_writes_title_and_time_in_one_xmp_packet(self):
        self.put('a.jpg', self.source())
        self.put('b.jpg', f.fx.jpeg(exif=False, xmp=None, seed=3))
        result = self.run_op(self.doc(['descriptive', 'captureTime']), 'r1g')
        self.assertEqual((result['written'], result['failed']), (1, 0))
        data = self.read('r1g', 'photos/b.jpg')
        got = snapshot(data, fields=['title', 'captureTime'])
        self.assertEqual((got['title']['value']['text'], got['captureTime']['value']), ('Harbour', self.TIME))
        self.assertEqual(f.fx.exif_ascii(data, 'ExifIFD', 0x9003), None)
        self.assertEqual(self.verify('r1g')['nativeReplay'], 'fresh-replay-matched')

    def test_E4R3_a_mixed_selection_whose_location_is_already_equal_leaves_it_unchanged_and_writes_the_rest(self):
        gps = dict(self.GPS)
        self.put('a.jpg', f.fx.jpeg(make='A', model='M', exif_version=b'0300', gps=gps, xmp=f.fx.xmp_properties(extra=f.lang_alt('dc:title', 'Harbour'))))
        self.put('b.jpg', f.fx.jpeg(make='B', model='X', exif_version=b'0300', gps=gps, seed=2))
        result = self.run_op(self.doc(['descriptive', 'location']), 'r3i')
        self.assertEqual((result['written'], result['failed']), (1, 0))
        decisions = {d['field']: (d['action'], d['reason']) for d in self.item('r3i')['decisions']}
        self.assertEqual((decisions['title'], decisions['location']), (('write', 'destinationAbsent'), ('unchanged', 'equal')))
        self.assertEqual(self.verify('r3i')['nativeReplay'], 'fresh-replay-matched')

    def test_E4R1_a_time_into_a_gps_only_height_destination_creates_no_exififd_and_keeps_the_height_meaning(self):
        gps = {'version': (2, 4, 0, 0), 'lat': [(10, 1), (0, 1), (0, 1)], 'lon': [(20, 1), (0, 1), (0, 1)], 'alt': (12, 1), 'alt_ref': 0}
        self.put('a.jpg', self.source())
        self.put('b.jpg', f.fx.jpeg(make='B', model='X', gps=gps, exif_version=None, dto=None, off=None, sub=None, exif_extra=[]))
        result = self.run_op(self.doc(['captureTime']), 'r1h')
        self.assertEqual(result['written'], 1)
        row = self.item('r1h')
        self.assertEqual(row['arguments'], ['-n', '-XMP-exif:DateTimeOriginal=2024-03-01T10:20:30.25+09:00'])      # one XMP carrier: no ExifIFD, hence no ExifVersion, is created
        data = self.read('r1h', 'photos/b.jpg')
        self.assertEqual(f.fx.exif_ascii(data, 'ExifIFD', 0x9003), None)
        from schemaxis.adaptors.exiftool import containers, e3read, records
        before = e3read.height(records.Payloads(containers.locate((self.media / 'b.jpg').read_bytes())))
        after = e3read.height(records.Payloads(containers.locate(data)))
        self.assertEqual((before['state'], before['reference'], after['state'], after['reference']), ('present', 'ellipsoidal', 'present', 'ellipsoidal'))
        self.assertEqual(snapshot(data, fields=['captureTime'])['captureTime']['value'], self.TIME)
        self.assertEqual(self.verify('r1h')['nativeReplay'], 'fresh-replay-matched')

    def test_E4R1_an_offset_less_source_never_invents_a_zone_and_never_removes_a_destination_offset(self):
        self.put('a.jpg', self.source(off=None))
        self.put('b.jpg', self.timeless(off='+02:00'))
        fault = self.refuses(self.doc(['captureTime']), 'r1d', 'NO_USABLE_ITEMS')
        self.assertEqual(fault.observed['firstFaults'][1]['code'], 'TRANSFER_TIME_OFFSET_CONFLICT')
        self.put('b.jpg', self.timeless())
        self.run_op(self.doc(['captureTime']), 'r1e')
        self.assertEqual(self.time_of(self.read('r1e', 'photos/b.jpg')), ('2024:03:01 10:20:30', None, '25'))       # the zone is absent, not invented

    def test_E4R1_a_selected_time_the_planner_does_not_apply_is_refused_never_reported_unchanged(self):
        from unittest import mock
        from schemaxis.adaptors.exiftool import e3write
        self.put('a.jpg', self.source(xmp=f.fx.xmp_properties(extra=f.lang_alt('dc:title', 'Harbour'))))
        self.put('b.jpg', self.timeless())
        with mock.patch.object(e3write, 'time_plan', lambda *a, **k: e3write.unchanged_plan('noTimeFieldPresent')):
            fault = self.refuses(self.doc(['descriptive', 'captureTime']), 'r1f', 'NO_USABLE_ITEMS')
        self.assertEqual(fault.observed['firstFaults'][1]['code'], 'TRANSFER_TIME_NOT_APPLIED')
        self.assertFalse((self.tmp / 'r1f' / 'photos').exists() and list((self.tmp / 'r1f' / 'photos').glob('b.jpg')))

    def test_E4R2_every_language_alternative_is_carried_exactly_and_a_blank_one_is_refused_without_a_placeholder(self):
        title = f.lang_alt('dc:title', 'e\u0301 ', de_DE='Hafen ', fr='\u00e9t\u00e9 ')
        self.put('a.jpg', f.fx.jpeg(make='A', model='M', xmp=f.fx.xmp_properties(extra=title)))
        self.put('b.jpg', f.plain())
        self.run_op(self.doc(['descriptive']), 'r2a')
        value = snapshot(self.read('r2a', 'photos/b.jpg'), fields=['title'])['title']['value']
        self.assertEqual((value['text'], sorted((e['language'], e['text']) for e in value['languages'])), ('e\u0301 ', [('de-DE', 'Hafen '), ('fr', '\u00e9t\u00e9 ')]))
        self.assertEqual(self.verify('r2a')['nativeReplay'], 'fresh-replay-matched')
        self.put('a.jpg', f.fx.jpeg(make='A', model='M', xmp=f.fx.xmp_properties(extra=f.lang_alt('dc:title', 'Harbour', de_DE='  '))))
        fault = self.refuses(self.doc(['descriptive']), 'r2b', 'NO_USABLE_ITEMS')
        first = fault.observed['firstFaults'][1]
        self.assertEqual((first['code'], first['observed']['cause']), ('TRANSFER_VALUE_NOT_REPRESENTABLE', 'EDIT_EMPTY_VALUE'))
        self.assertFalse((self.tmp / 'r2b' / 'photos').exists())

    def planner_mutant_fault(self, name, groups, patcher, src, dst, location):
        self.put('a.jpg', src)
        self.put('b.jpg', dst)
        with patcher():
            fault = self.refuses(self.doc(groups), name, 'NO_USABLE_ITEMS')
        first = fault.observed['firstFaults'][1]
        self.assertEqual((first['code'], first['location']), ('TRANSFER_READBACK_MISMATCH', location))
        self.assertFalse((self.tmp / name / 'photos').exists())

    def time_mutant(self):
        from unittest import mock
        from schemaxis.adaptors.exiftool import e3time
        real = e3time.absolute_target
        return mock.patch.object(e3time, 'absolute_target', lambda absolute, group, at: (lambda t: (t[0] + 10 ** 9, t[1], t[2]))(real(absolute, group, at)))

    def location_mutant(self):
        from unittest import mock
        real = e4copy.location_request

        def shifted(src_row, losses):
            request, quantisation = real(src_row, losses)
            from decimal import Decimal
            return {**request, 'latitude': format(Decimal(request['latitude']) + Decimal('0.000001'), 'f')}, quantisation
        return mock.patch.object(e4copy, 'location_request', shifted)

    def test_E4R3_a_time_planner_mutant_is_caught_by_the_independent_proof_t_for_single_and_mixed_selections(self):
        self.planner_mutant_fault('r3a', ['captureTime'], self.time_mutant, self.source(), self.source(dto='2020:01:01 00:00:00', off='+00:00', sub='12', seed=2), '$.items[1].fields.captureTime')
        self.planner_mutant_fault('r3b', ['descriptive', 'captureTime'], self.time_mutant, self.source(), self.source(dto='2020:01:01 00:00:00', off='+00:00', sub='12', seed=2), '$.items[1].fields.captureTime')
        self.planner_mutant_fault('r3c', ['captureTime'], self.time_mutant, self.source(), self.timeless(), '$.items[1].fields.captureTime')

    def test_E4R3_a_location_planner_mutant_is_caught_by_the_independent_proof_t_for_single_and_mixed_selections(self):
        src = f.fx.jpeg(make='A', model='M', exif_version=b'0300', gps=self.GPS, xmp=f.fx.xmp_properties(extra=f.lang_alt('dc:title', 'Harbour')))
        dst = f.fx.jpeg(make='B', model='X', exif_version=b'0300', seed=2)
        self.planner_mutant_fault('r3d', ['location'], self.location_mutant, src, dst, '$.items[1].fields.location.latitude')
        self.planner_mutant_fault('r3e', ['descriptive', 'location'], self.location_mutant, src, dst, '$.items[1].fields.location.latitude')

    def test_E4R3_a_source_coordinate_beyond_nine_decimals_is_quantised_half_even_and_still_verifies(self):
        gps = dict(self.GPS, lat=[(35, 1), (7, 1), (2412345679, 10 ** 8)], lon=[(139, 1), (45, 1), (36, 1)])
        self.put('a.jpg', f.fx.jpeg(make='A', model='M', exif_version=b'0300', gps=gps))
        self.put('b.jpg', f.fx.jpeg(make='B', model='X', exif_version=b'0300', seed=2))
        self.run_op(self.doc(['location']), 'r3f')
        row = self.item('r3f')
        self.assertEqual(sorted(row['proofs']), ['N', 'P', 'R', 'T', 'problems'])
        planned = {e['id']: e for e in self.json('r3f', 'transfer-plan.json')['items']}['b']
        self.assertEqual(planned['quantisation']['latitude']['written'], '35.123367627')           # 35 + 7/60 + 24.12345679/3600 degrees, half-even to nine places
        self.assertGreater(planned['quantisation']['latitude']['differenceDegrees'], 0)
        self.assertEqual(self.verify('r3f')['nativeReplay'], 'fresh-replay-matched')
        self.assertTrue(any(key.startswith('location:GPS:GPSLatitude') for key in row['proofs']['T']['nativeKeysCompared']))

    def test_E4R3_a_changed_coordinate_degree_in_the_published_single_location_output_is_a_transfer_readback_mismatch(self):
        self.put('a.jpg', f.fx.jpeg(make='A', model='M', exif_version=b'0300', gps=self.GPS))
        self.put('b.jpg', f.fx.jpeg(make='B', model='X', exif_version=b'0300', seed=2))
        self.run_op(self.doc(['location']), 'r3g')
        pair = (35).to_bytes(4, 'little') + (1).to_bytes(4, 'little')
        raw = self.read('r3g', 'photos/b.jpg')
        self.assertEqual(raw.count(pair), 1)

        def change(target):
            path = target / 'photos' / 'b.jpg'
            path.write_bytes(path.read_bytes().replace(pair, (34).to_bytes(4, 'little') + (1).to_bytes(4, 'little'), 1))
        code, location = f.mutate_and_refresh(self, 'r3g', 'single-location', change, 'TRANSFER_READBACK_MISMATCH')
        self.assertIn('fields.location', location)

    def test_E4R3_a_changed_time_in_the_published_single_time_output_is_a_transfer_readback_mismatch(self):
        self.put('a.jpg', self.source())
        self.put('b.jpg', self.timeless())
        self.run_op(self.doc(['captureTime']), 'r3h')

        def change(target):
            path = target / 'photos' / 'b.jpg'
            data = path.read_bytes()
            assert data.count(b'2024:03:01 10:20:30') == 1
            path.write_bytes(data.replace(b'2024:03:01 10:20:30', b'2024:03:01 10:20:31', 1))
        code, location = f.mutate_and_refresh(self, 'r3h', 'single-time', change, 'TRANSFER_READBACK_MISMATCH')
        self.assertEqual(location, '$.items[1].fields.captureTime')

    def full(self, **kw):
        base = dict(make='B', seed=2, dto='2020:01:01 00:00:00', off='+00:00', sub='12', xmp=f.fx.xmp_properties(captured='2020-01-01T00:00:00.12+00:00'),
                    iptc=[(2, 55, '20200101'), (2, 60, '000000+0000'), (2, 120, b'unrequested caption')])
        base.update(kw)
        return f.fx.full_time(**base)

    def full_source(self):
        return f.fx.full_time(make='A', dto='2024:03:01 10:20:30', off='+09:00', sub='25', xmp=f.fx.xmp_properties(captured='2024-03-01T10:20:30.25+09:00', extra=f.lang_alt('dc:title', 'Harbour')),
                              iptc=[(2, 55, '20240301'), (2, 60, '102030+0900')])

    def test_E4R5_every_selection_with_the_capture_time_succeeds_into_a_three_family_destination(self):
        for name, groups in (('r5a', ['captureTime']), ('r5b', ['descriptive', 'captureTime']), ('r5c', ['camera', 'captureTime']), ('r5d', ['descriptive', 'camera', 'captureTime'])):
            self.put('a.jpg', self.full_source())
            self.put('b.jpg', self.full())
            result = self.run_op(self.doc(groups), name)
            self.assertEqual((result['written'], result['failed']), (1, 0), name)
            data = self.read(name, 'photos/b.jpg')
            self.assertEqual(self.time_of(data), ('2024:03:01 10:20:30', '+09:00', '25'), name)
            self.assertIn(b'20240301', data)
            self.assertIn(b'102030+0900', data)
            self.assertIn(b'unrequested caption', data)                       # an unrequested IPTC dataset keeps its bytes
            self.assertEqual(self.verify(name)['nativeReplay'], 'fresh-replay-matched', name)

    def test_M_E4R5_an_unrequested_iptc_dataset_changed_in_a_mixed_output_still_fails_the_untouched_data_guard(self):
        self.put('a.jpg', self.full_source())
        self.put('b.jpg', self.full())
        self.run_op(self.doc(['camera', 'captureTime']), 'r5m')

        def change(target):
            path = target / 'photos' / 'b.jpg'
            data = path.read_bytes()
            assert data.count(b'unrequested caption') == 1
            path.write_bytes(data.replace(b'unrequested caption', b'unrequested captioN', 1))
        code, location = f.mutate_and_refresh(self, 'r5m', 'iptc-unrequested', change, 'UNREQUESTED_METADATA_CHANGED')
        self.assertEqual(location, '$.items[1].iptc')

    def test_E4R6_an_absent_source_and_an_absent_destination_are_unchanged_while_a_present_destination_still_refuses_a_clear(self):
        gps_less = dict(make='A', model='M', exif_version=b'0300', dto=None, off=None, sub=None)
        self.put('a.jpg', f.fx.jpeg(**gps_less))
        self.put('b.jpg', f.fx.jpeg(**dict(gps_less, make='B', seed=2)))
        for name, groups in (('r6a', ['captureTime']), ('r6b', ['location'])):
            fault = self.refuses(self.doc(groups, policies={'absent': 'clearDestination'}), name, 'NO_USABLE_ITEMS')
            first = fault.observed['firstFaults'][1]
            self.assertEqual((first['code'], first['observed']['reason']), ('ITEM_UNCHANGED', 'sourceAbsent'), name)
        self.put('b.jpg', f.fx.jpeg(make='B', model='X', exif_version=b'0300', gps=self.GPS, seed=2))
        fault = self.refuses(self.doc(['location'], policies={'absent': 'clearDestination'}), 'r6c', 'NO_USABLE_ITEMS')
        self.assertEqual(fault.observed['firstFaults'][1]['code'], 'TRANSFER_E3_CLEAR_UNSUPPORTED')

    def test_M_E4R4_an_nfc_and_strip_reader_mutant_that_lets_the_host_comparison_agree_is_caught_by_the_native_listing_comparison(self):
        import unicodedata
        from unittest import mock
        title = 'e\u0301 '
        self.put('c.jpg', f.fx.jpeg(make='C', model='M', xmp=f.fx.xmp_properties(extra=f.lang_alt('dc:title', title)), seed=5))
        self.put('d.jpg', f.fx.jpeg(make='D', model='X', seed=6))
        self.run_op({**COPY, 'media': self.items('c', 'd'), 'source': {'item': 'c'}, 'transfer': {'groups': ['descriptive']}}, 'r4base')
        mangled = ('e\u0301 '.encode('utf-8'), '\u00e9  '.encode('utf-8'))
        real = e4model.snapshot

        def norm(value):
            if isinstance(value, str):
                return unicodedata.normalize('NFC', value).strip()
            if isinstance(value, list):
                return [norm(x) for x in value]
            if isinstance(value, dict):
                return {k: norm(x) for k, x in value.items()}
            return value

        def reader(*args, **kwargs):
            snap = real(*args, **kwargs)
            for row in snap.values():
                if isinstance(row, dict) and 'value' in row:
                    row['value'] = norm(row['value'])
            return snap

        def change(target):
            path = target / 'photos' / 'd.jpg'
            data = path.read_bytes()
            assert mangled[0] in data
            path.write_bytes(data.replace(mangled[0], mangled[1], 1))
        code, location, message = f.mutate_and_refresh(self, 'r4base', 'cm1-reader', change, 'TRANSFER_READBACK_MISMATCH', during=lambda: mock.patch.object(e4model, 'snapshot', reader))
        self.assertEqual(location, '$.items[1].native')
        self.assertEqual(message, 'the fixed ExifTool listing of the output differs from that of the source at the same key')


    # ---- E4F-1: a capture time that the output records only in IPTC 2:55 and 2:60 is compared natively at that carrier, never skipped and never reported as a mismatch of the right output
    PAIR = ['-IPTC:DateCreated=20240301', '-IPTC:TimeCreated=102030+0900']

    def iptc_only(self, **kw):
        base = dict(make='B', model='X', dto=None, off=None, sub=None, exif_version=b'0300', seed=2, iptc=[(2, 55, '20200101'), (2, 60, '000000+0000')])
        base.update(kw)
        return f.fx.jpeg(**base)

    def iptc_source(self, **kw):
        base = dict(make='A', model='M', dto=None, off=None, sub=None, exif_version=b'0300', iptc=[(2, 55, '20240301'), (2, 60, '102030+0900')])
        base.update(kw)
        return f.fx.jpeg(**base)

    def written(self, groups, name):
        """The transfer's result; a refusal of a transfer that must be written fails the test with the refusal's codes (never an unexplained error)."""
        try:
            return self.run_op(self.doc(groups), name)
        except SchemaxisError as error:
            first = [(x.get('code'), x.get('location')) for x in error.fault.to_dict().get('observed', {}).get('firstFaults', [])]
            self.fail('the transfer %s was refused (%s) instead of written: %s' % (name, error.fault.code, first))

    def iptc_time_of(self, data):
        return (f.fx.iim_value(data, 2, 55), f.fx.iim_value(data, 2, 60))

    def assert_iptc_time_written(self, name, groups, exif):
        self.put('a.jpg', self.source(sub=None))
        self.put('b.jpg', self.iptc_only(exif=exif))
        result = self.written(groups, name)
        self.assertEqual((result['written'], result['failed']), (1, 0), name)
        data = self.read(name, 'photos/b.jpg')
        self.assertEqual(self.iptc_time_of(data), ('20240301', '102030+0900'), name)
        self.assertEqual(self.time_of(data), (None, None, None), name)                 # no Exif capture time is created beside the IPTC pair
        row = self.item(name)
        self.assertEqual([a for a in row['arguments'] if 'DateCreated' in a or 'TimeCreated' in a], self.PAIR, name)
        self.assertEqual((row['status'], row['outcome']), ('written', 'transferred'), name)
        self.assertIn('captureTime', row['proofs']['T']['nativeKeysCompared'], name)          # T-native read the capture time of the source and of the output
        self.assertEqual(self.verify(name)['nativeReplay'], 'fresh-replay-matched', name)
        return data

    def test_E4F1_a_single_captured_time_is_written_and_verified_into_an_iptc_only_time_destination_with_and_without_an_exif_block(self):
        self.assert_iptc_time_written('f1a', ['captureTime'], True)
        self.assert_iptc_time_written('f1c', ['captureTime'], False)

    def test_E4F1_a_mixed_selection_with_a_captured_time_is_written_and_verified_into_an_iptc_only_time_destination_with_and_without_an_exif_block(self):
        for name, exif in (('f1b', True), ('f1d', False)):
            data = self.assert_iptc_time_written(name, ['descriptive', 'captureTime'], exif)
            self.assertEqual(snapshot(data, fields=['title'])['title']['value']['text'], 'Harbour', name)

    def test_E4F1_an_iptc_source_time_transfers_to_an_iptc_only_and_to_an_exif_destination_and_is_compared_natively(self):
        self.put('a.jpg', self.iptc_source())
        self.put('b.jpg', self.iptc_only())
        self.written(['captureTime'], 'f1e')
        data = self.read('f1e', 'photos/b.jpg')
        self.assertEqual(self.iptc_time_of(data), ('20240301', '102030+0900'))
        row = self.item('f1e')
        self.assertEqual([a for a in row['arguments'] if 'Created' in a], self.PAIR)
        self.assertIn('captureTime', row['proofs']['T']['nativeKeysCompared'])         # an IPTC source into an IPTC destination is compared, not skipped
        self.assertEqual(self.verify('f1e')['nativeReplay'], 'fresh-replay-matched')
        self.put('b.jpg', self.timeless())
        self.written(['captureTime'], 'f1f')
        self.assertEqual(self.time_of(self.read('f1f', 'photos/b.jpg')), ('2024:03:01 10:20:30', '+09:00', None))           # an IPTC source carries no fraction, and none is invented
        self.assertIn('captureTime', self.item('f1f')['proofs']['T']['nativeKeysCompared'])
        self.assertEqual(self.verify('f1f')['nativeReplay'], 'fresh-replay-matched')

    def test_E4F1_a_source_fraction_is_still_refused_into_an_iptc_only_time_destination_for_single_and_mixed_selections(self):
        for name, groups in (('f1h', ['captureTime']), ('f1i', ['descriptive', 'captureTime'])):
            self.put('a.jpg', self.source())                                           # the source records the fraction 25
            self.put('b.jpg', self.iptc_only())
            fault = self.refuses(self.doc(groups), name, 'NO_USABLE_ITEMS')
            first = fault.observed['firstFaults'][1]
            self.assertEqual((first['code'], first['location']), ('TIME_SUBSECOND_REQUIRED', 'captured/b.jpg'), name)
            self.assertFalse((self.tmp / name / 'photos').exists(), name)

    def iptc_output_change(self, old, new):
        def change(target):
            path = target / 'photos' / 'b.jpg'
            data = path.read_bytes()
            assert data.count(old) == 1
            path.write_bytes(data.replace(old, new, 1))
        return change

    def test_M_E4F1_a_changed_iptc_output_time_in_the_published_single_output_is_a_transfer_readback_mismatch(self):
        self.put('a.jpg', self.source(sub=None))
        self.put('b.jpg', self.iptc_only())
        self.written(['captureTime'], 'f1m')
        for label, old, new in (('iptc-second', b'102030+0900', b'102031+0900'), ('iptc-offset', b'102030+0900', b'102030+0800'), ('iptc-date', b'20240301', b'20240302')):
            code, location = f.mutate_and_refresh(self, 'f1m', label, self.iptc_output_change(old, new), 'TRANSFER_READBACK_MISMATCH')
            self.assertEqual(location, '$.items[1].fields.captureTime', label)

    def test_M_E4F1_a_changed_iptc_output_time_in_the_published_mixed_output_is_a_transfer_readback_mismatch(self):
        self.put('a.jpg', self.source(sub=None))
        self.put('b.jpg', self.iptc_only(exif=False))
        self.written(['descriptive', 'captureTime'], 'f1n')
        code, location = f.mutate_and_refresh(self, 'f1n', 'iptc-mixed-second', self.iptc_output_change(b'102030+0900', b'102031+0900'), 'TRANSFER_READBACK_MISMATCH')
        self.assertEqual(location, '$.items[1].fields.captureTime')

    def test_M_E4F1_a_reader_that_hides_the_changed_iptc_time_from_the_host_comparison_is_caught_by_the_native_listing_comparison(self):
        from unittest import mock
        self.put('a.jpg', self.source(sub=None))
        self.put('b.jpg', self.iptc_only())
        self.written(['captureTime'], 'f1o')
        real = e4model.snapshot

        def reader(*args, **kwargs):
            snap = real(*args, **kwargs)
            row = snap.get('captureTime')
            if row and row.get('state') == 'present' and row['value'].get('local') == '2024-03-01T10:20:31':
                row['value'] = {**row['value'], 'local': '2024-03-01T10:20:30'}         # the host reader reports the source's second: only the native listing can tell
            return snap
        code, location, message = f.mutate_and_refresh(self, 'f1o', 'iptc-reader', self.iptc_output_change(b'102030+0900', b'102031+0900'), 'TRANSFER_READBACK_MISMATCH', during=lambda: mock.patch.object(e4model, 'snapshot', reader))
        self.assertEqual(location, '$.items[1].native')
        self.assertEqual(message, 'the fixed ExifTool listing of the output states another capture time than that of the source')


    # ---- E4F-2: a whole-second captured time (no fraction, or no offset) into a destination without Exif or XMP is written into one new XMP carrier and verified, never refused
    XMP_TIME = b'<exif:DateTimeOriginal>2024-03-01T10:20:30+09:00</exif:DateTimeOriginal>'

    def blank(self, **kw):
        return f.fx.jpeg(**{**dict(exif=False, xmp=None, seed=3), **kw})

    def title_xmp(self):
        return f.fx.xmp_properties(extra=f.lang_alt('dc:title', 'Harbour'))

    def assert_whole_second_written(self, name, source, groups, xmp_bytes, argument, local, offset):
        self.put('a.jpg', source)
        self.put('b.jpg', self.blank())
        result = self.written(groups, name)
        self.assertEqual((result['written'], result['failed']), (1, 0), name)
        data = self.read(name, 'photos/b.jpg')
        self.assertIn(xmp_bytes, data, name)
        self.assertEqual((self.time_of(data), self.iptc_time_of(data)), (((None, None, None)), (None, None)), name)               # one new XMP carrier: no Exif capture time and no IPTC pair are created
        self.assertEqual(snapshot(data, fields=['captureTime'])['captureTime']['value'], {'local': local, 'offset': offset, 'sub': None}, name)
        row = self.item(name)
        self.assertEqual([a for a in row['arguments'] if 'DateTimeOriginal' in a], [argument], name)
        self.assertTrue(any(l.get('reason') == 'timeCreatedInXmpOnly' for l in row['losses']), name)
        self.assertIn('captureTime', row['proofs']['T']['nativeKeysCompared'], name)
        self.assertEqual(self.verify(name)['nativeReplay'], 'fresh-replay-matched', name)
        return data

    def test_E4F2_a_whole_second_exif_or_iptc_time_is_written_and_verified_into_a_blank_destination_as_a_single_selection(self):
        argument = '-XMP-exif:DateTimeOriginal=2024-03-01T10:20:30+09:00'
        self.assert_whole_second_written('f2a', self.source(sub=None), ['captureTime'], self.XMP_TIME, argument, '2024-03-01T10:20:30', '+09:00')
        self.assert_whole_second_written('f2b', self.iptc_source(), ['captureTime'], self.XMP_TIME, argument, '2024-03-01T10:20:30', '+09:00')

    def test_E4F2_a_whole_second_exif_or_iptc_time_is_written_and_verified_into_a_blank_destination_in_a_mixed_selection(self):
        argument = '-XMP-exif:DateTimeOriginal=2024-03-01T10:20:30+09:00'
        for name, source in (('f2c', self.source(sub=None)), ('f2d', self.iptc_source(xmp=self.title_xmp()))):
            data = self.assert_whole_second_written(name, source, ['descriptive', 'captureTime'], self.XMP_TIME, argument, '2024-03-01T10:20:30', '+09:00')
            self.assertEqual(snapshot(data, fields=['title'])['title']['value']['text'], 'Harbour', name)

    def test_E4F2_a_source_without_an_offset_never_gets_an_invented_zone_in_a_new_xmp_carrier_and_a_fraction_is_kept(self):
        self.assert_whole_second_written('f2e', self.source(sub=None, off=None), ['captureTime'], b'<exif:DateTimeOriginal>2024-03-01T10:20:30</exif:DateTimeOriginal>',
                                         '-XMP-exif:DateTimeOriginal=2024-03-01T10:20:30', '2024-03-01T10:20:30', None)
        self.put('a.jpg', self.source(off=None))                                                         # offset-less with the fraction 25
        self.put('b.jpg', self.blank())
        self.written(['captureTime'], 'f2f')
        data = self.read('f2f', 'photos/b.jpg')
        self.assertIn(b'<exif:DateTimeOriginal>2024-03-01T10:20:30.25</exif:DateTimeOriginal>', data)
        self.assertEqual(snapshot(data, fields=['captureTime'])['captureTime']['value'], {'local': '2024-03-01T10:20:30', 'offset': None, 'sub': '25'})
        self.assertEqual(self.verify('f2f')['nativeReplay'], 'fresh-replay-matched')

    def test_M_E4F2_a_changed_or_dropped_time_in_the_published_blank_destination_output_is_still_a_transfer_readback_mismatch(self):
        self.put('a.jpg', self.source(sub=None))
        self.put('b.jpg', self.blank())
        self.written(['captureTime'], 'f2m')

        def replace(old, new):
            def change(target):
                path = target / 'photos' / 'b.jpg'
                data = path.read_bytes()
                assert data.count(old) == 1
                path.write_bytes(data.replace(old, new, 1))
            return change
        for label, old, new in (('xmp-second', b'10:20:30+09:00<', b'10:20:31+09:00<'), ('xmp-offset', b'10:20:30+09:00<', b'10:20:30+08:00<'), ('xmp-date', b'2024-03-01T', b'2024-03-02T')):
            code, location = f.mutate_and_refresh(self, 'f2m', label, replace(old, new), 'TRANSFER_READBACK_MISMATCH')
            self.assertEqual(location, '$.items[1].fields.captureTime', label)


    # ---- E4G-1: one capture time that the source spreads over carriers (the Exif local time without its offset or fraction, the offset or fraction stated by IPTC 2:60, XMP photoshop or XMP exif) is
    # written, compared natively as ONE time with every component any carrier states, and verified. Every expected value is a literal.
    IPTC9 = [(2, 55, '20240301'), (2, 60, '102030+0900')]
    FRACTION_KINDS = ('xmp-exif', 'split', 'pure-xmp-exif')

    def spread_source(self, kind, mixed=False):
        title = f.lang_alt('dc:title', 'Harbour') if mixed else ''
        shared = dict(make='A', model='M', dto='2024:03:01 10:20:30', off=None, sub=None, exif_version=b'0300')
        photoshop, xmp_exif = f.fx.xmp_properties(captured='2024-03-01T10:20:30+09:00', extra=title), f.fx.xmp_properties(exif_dto='2024-03-01T10:20:30.25+09:00', extra=title)
        plain_xmp = f.fx.xmp_properties(extra=title) or None
        extra = {'iptc': dict(iptc=self.IPTC9, xmp=plain_xmp),                              # Exif without offset, IPTC 2:60 states +0900
                 'photoshop': dict(xmp=photoshop),                                          # Exif without offset, XMP photoshop states +09:00
                 'xmp-exif': dict(xmp=xmp_exif),                                            # Exif without offset or fraction, XMP exif states .25+09:00
                 'split': dict(sub='25', iptc=self.IPTC9, xmp=plain_xmp),                   # the fraction in Exif, the offset in IPTC
                 'redundant': dict(off='+09:00', iptc=self.IPTC9, xmp=photoshop),          # every carrier states the same offset: a control
                 'pure-photoshop': dict(dto=None, xmp=photoshop),                           # one carrier only, no Exif time
                 'pure-xmp-exif': dict(dto=None, xmp=xmp_exif)}[kind]
        return f.fx.jpeg(**{**shared, **extra})

    def spread_destination(self, kind):
        return {'replace': lambda: f.fx.jpeg(make='B', model='X', dto='2020:01:01 00:00:00', off='+00:00', sub=None, exif_version=b'0300', seed=2),
                'timeless': self.timeless, 'blank': self.blank, 'iptc': self.iptc_only}[kind]()

    def assert_spread_written(self, name, kind, destination, groups):
        self.put('a.jpg', self.spread_source(kind, mixed='descriptive' in groups))
        self.put('b.jpg', self.spread_destination(destination))
        result = self.written(groups, name)
        self.assertEqual((result['written'], result['failed']), (1, 0), name)
        data = self.read(name, 'photos/b.jpg')
        fraction = '25' if kind in self.FRACTION_KINDS else None
        if destination in ('replace', 'timeless'):
            self.assertEqual(self.time_of(data), ('2024:03:01 10:20:30', '+09:00', fraction), name)
        elif destination == 'blank':
            self.assertIn(('<exif:DateTimeOriginal>2024-03-01T10:20:30%s+09:00</exif:DateTimeOriginal>' % ('.25' if fraction else '')).encode(), data, name)
            self.assertEqual((self.time_of(data), self.iptc_time_of(data)), ((None, None, None), (None, None)), name)
        else:
            self.assertEqual((self.iptc_time_of(data), self.time_of(data)), (('20240301', '102030+0900'), (None, None, None)), name)
        self.assertEqual(snapshot(data, fields=['captureTime'])['captureTime']['value'], {'local': '2024-03-01T10:20:30', 'offset': '+09:00', 'sub': fraction}, name)
        row = self.item(name)
        self.assertEqual((row['status'], row['outcome']), ('written', 'transferred'), name)
        self.assertIn('captureTime', row['proofs']['T']['nativeKeysCompared'], name)
        self.assertEqual(self.verify(name)['nativeReplay'], 'fresh-replay-matched', name)
        if 'descriptive' in groups:
            self.assertEqual(snapshot(data, fields=['title'])['title']['value']['text'], 'Harbour', name)
        return data

    def test_E4G1_a_time_spread_over_carriers_is_written_and_verified_into_destinations_that_record_a_time_or_none_as_a_single_selection(self):
        for number, (kind, destination) in enumerate((k, d) for k in ('iptc', 'photoshop', 'xmp-exif', 'split', 'redundant', 'pure-photoshop', 'pure-xmp-exif') for d in ('replace', 'timeless', 'blank')):
            self.assert_spread_written('g1s%d' % number, kind, destination, ['captureTime'])

    def test_E4G1_a_time_spread_over_carriers_is_written_and_verified_into_an_iptc_only_time_destination_when_it_has_no_fraction(self):
        for number, kind in enumerate(('iptc', 'photoshop', 'redundant', 'pure-photoshop')):
            self.assert_spread_written('g1i%d' % number, kind, 'iptc', ['captureTime'])

    def test_E4G1_a_time_spread_over_carriers_is_written_and_verified_in_a_mixed_selection(self):
        for number, (kind, destination) in enumerate((k, d) for k in ('iptc', 'photoshop', 'xmp-exif', 'split') for d in ('replace', 'timeless', 'blank')):
            self.assert_spread_written('g1m%d' % number, kind, destination, ['descriptive', 'captureTime'])
        for number, kind in enumerate(('iptc', 'photoshop')):
            self.assert_spread_written('g1j%d' % number, kind, 'iptc', ['descriptive', 'captureTime'])

    def test_E4G1_a_fraction_spread_over_carriers_is_still_refused_into_an_iptc_only_time_destination(self):
        for name, kind, groups in (('g1r0', 'xmp-exif', ['captureTime']), ('g1r1', 'split', ['captureTime']), ('g1r2', 'xmp-exif', ['descriptive', 'captureTime'])):
            self.put('a.jpg', self.spread_source(kind, mixed='descriptive' in groups))
            self.put('b.jpg', self.iptc_only())
            fault = self.refuses(self.doc(groups), name, 'NO_USABLE_ITEMS')
            first = fault.observed['firstFaults'][1]
            self.assertEqual((first['code'], first['location']), ('TIME_SUBSECOND_REQUIRED', 'captured/b.jpg'), name)
            self.assertFalse((self.tmp / name / 'photos').exists(), name)

    def test_E4G1_a_source_whose_carriers_disagree_on_the_offset_the_fraction_or_the_second_is_refused_before_anything_is_written(self):
        conflicting = {'offset': dict(dto='2024:03:01 10:20:30', off='+09:00', sub=None, iptc=[(2, 55, '20240301'), (2, 60, '102030+0800')]),
                       'fraction': dict(dto='2024:03:01 10:20:30', off=None, sub='26', xmp=f.fx.xmp_properties(exif_dto='2024-03-01T10:20:30.25+09:00')),
                       'second': dict(dto='2024:03:01 10:20:30', off='+09:00', sub=None, xmp=f.fx.xmp_properties(captured='2024-03-01T10:20:31+09:00'))}
        for number, (label, kw) in enumerate(conflicting.items()):
            name = 'g1c%d' % number
            self.put('a.jpg', f.fx.jpeg(**{**dict(make='A', model='M', exif_version=b'0300'), **kw}))
            self.put('b.jpg', self.spread_destination('replace'))
            fault = self.refuses(self.doc(['captureTime']), name, 'NO_USABLE_ITEMS')
            self.assertFalse((self.tmp / name / 'photos').exists(), label)
            first = fault.observed['firstFaults'][1]
            self.assertEqual((first['code'], first['location']), ('TRANSFER_SOURCE_AMBIGUOUS', '$.transfer.captureTime'), label)

    def spread_output_change(self, old, new):
        def change(target):
            path = target / 'photos' / 'b.jpg'
            data = path.read_bytes()
            assert data.count(old) == 1, (old, data.count(old))
            path.write_bytes(data.replace(old, new, 1))
        return change

    def host_blind(self, component, wrong, right):
        """A reader mutant: the host snapshot of the output reports the source's ``component`` where the output states ``wrong``, so only the native listing comparison can tell."""
        from unittest import mock
        real = e4model.snapshot

        def reader(*args, **kwargs):
            snap = real(*args, **kwargs)
            row = snap.get('captureTime')
            if row and row.get('state') == 'present' and row['value'].get(component) == wrong:
                row['value'] = {**row['value'], component: right}
            return snap
        return lambda: mock.patch.object(e4model, 'snapshot', reader)

    NATIVE_MESSAGE = 'the fixed ExifTool listing of the output states another capture time than that of the source'

    def assert_spread_mutants(self, name, kind, destination, groups, mutants, blind):
        """Every semantic mutant of a published spread-source output is refused at the host comparison; the ``blind`` ones, with the host reader hidden, at the native listing comparison."""
        self.put('a.jpg', self.spread_source(kind, mixed='descriptive' in groups))
        self.put('b.jpg', self.spread_destination(destination))
        self.written(groups, name)
        for label, old, new in mutants:
            code, location = f.mutate_and_refresh(self, name, label, self.spread_output_change(old, new), 'TRANSFER_READBACK_MISMATCH')
            self.assertEqual(location, '$.items[1].fields.captureTime', label)
        for label, old, new, component, wrong, right in blind:
            code, location, message = f.mutate_and_refresh(self, name, label, self.spread_output_change(old, new), 'TRANSFER_READBACK_MISMATCH', during=self.host_blind(component, wrong, right))
            self.assertEqual((location, message), ('$.items[1].native', self.NATIVE_MESSAGE), label)

    def test_M_E4G1_a_wrong_offset_in_the_output_of_an_exif_time_with_an_iptc_or_xmp_offset_is_a_transfer_readback_mismatch_also_when_the_host_reader_hides_it(self):
        offset = (b'+09:00\x00', b'+08:00\x00')
        self.assert_spread_mutants('g1n0', 'iptc', 'replace', ['captureTime'], [('exif-offset-iptc-source', *offset)], [('exif-offset-iptc-source-blind', *offset, 'offset', '+08:00', '+09:00')])
        self.assert_spread_mutants('g1n1', 'photoshop', 'timeless', ['descriptive', 'captureTime'], [('exif-offset-photoshop-mixed', *offset)], [('exif-offset-photoshop-mixed-blind', *offset, 'offset', '+08:00', '+09:00')])
        self.assert_spread_mutants('g1n2', 'iptc', 'iptc', ['captureTime'], [('iptc-offset-iptc-source', b'102030+0900', b'102030+0800')], [('iptc-offset-iptc-source-blind', b'102030+0900', b'102030+0800', 'offset', '+08:00', '+09:00')])

    def test_M_E4G1_a_wrong_fraction_or_a_wrong_offset_and_fraction_in_the_output_of_a_time_spread_over_carriers_is_a_transfer_readback_mismatch_also_when_the_host_reader_hides_it(self):
        both = (b'10:20:30.25+09:00<', b'10:20:30.26+08:00<')
        self.assert_spread_mutants('g1n3', 'xmp-exif', 'blank', ['captureTime'], [('xmp-fraction', b'10:20:30.25+09:00<', b'10:20:30.26+09:00<'), ('xmp-fraction-and-offset', *both)],
                                   [('xmp-fraction-blind', b'10:20:30.25+09:00<', b'10:20:30.26+09:00<', 'sub', '26', '25')])
        self.assert_spread_mutants('g1n4', 'split', 'blank', ['descriptive', 'captureTime'], [('xmp-fraction-and-offset-mixed', *both)],
                                   [('xmp-offset-mixed-blind', b'10:20:30.25+09:00<', b'10:20:30.25+08:00<', 'offset', '+08:00', '+09:00')])


    # ---- E4H-1: a capture-time component (an offset or a fraction) that is stated only by a carrier which does not state the local time itself (Exif OffsetTimeOriginal or SubSecTimeOriginal
    # without Exif DateTimeOriginal, IPTC 2:60 without 2:55) is an "orphan". It is never attached to a local time another carrier states: the selected time is refused before any write with
    # TRANSFER_TIME_COMPONENT_UNANCHORED. A component that an anchored carrier states too is not orphaned (the orphan is redundant). Every expected value is a literal.
    ORPHAN_MESSAGE = 'the %s capture time cannot be used: its %s %s stated only by a carrier that does not state the local time itself, so no association with that time is invented'

    def orphan_source(self, kind, mixed=False):
        title = f.lang_alt('dc:title', 'Harbour') if mixed else ''
        shared = dict(make='A', model='M', exif_version=b'0300')
        return f.fx.jpeg(**{**shared, **{
            'o01': dict(dto=None, off='+09:00', sub=None, xmp=f.fx.xmp_properties(exif_dto='2024-03-01T10:20:30', extra=title)),                  # Exif offset, no Exif time; XMP exif whole second
            'o02': dict(dto=None, off=None, sub='25', xmp=f.fx.xmp_properties(captured='2024-03-01T10:20:30+09:00', extra=title)),                 # Exif fraction, no Exif time; XMP photoshop
            'o03': dict(dto='2024:03:01 10:20:30', off=None, sub=None, iptc=[(2, 60, '102030+0900')], xmp=f.fx.xmp_properties(extra=title) or None),   # IPTC time, no IPTC date
            'o04': dict(dto='2024:03:01 10:20:30', off=None, sub=None, iptc=[(2, 60, '235959+0900')], xmp=f.fx.xmp_properties(extra=title) or None),   # IPTC time of another clock, no IPTC date
            'o05': dict(dto=None, off='+09:00', sub=None, xmp=f.fx.xmp_properties(captured='2024-03-01T10:20:30+09:00', extra=title)),             # control: the Exif offset is redundant (XMP photoshop states it)
            'o06': dict(dto=None, off=None, sub='25', xmp=f.fx.xmp_properties(exif_dto='2024-03-01T10:20:30.25+09:00', extra=title)),              # control: the Exif fraction is redundant (XMP exif states it)
            'o07': dict(dto='2024:03:01 10:20:30', off=None, sub=None, iptc=[(2, 55, '20240301'), (2, 60, '102030+0900')], xmp=f.fx.xmp_properties(extra=title) or None),  # control: anchored IPTC
        }[kind]})

    ORPHAN_WHAT = {'o01': 'UTC offset', 'o02': 'fraction of a second', 'o03': 'UTC offset', 'o04': 'UTC offset'}

    def assert_orphan_refused(self, name, kind, destination, groups, dest_data=None):
        self.put('a.jpg', self.orphan_source(kind, mixed='descriptive' in groups))
        self.put('b.jpg', dest_data if dest_data is not None else self.spread_destination(destination))
        fault = self.refuses(self.doc(groups), name, 'NO_USABLE_ITEMS')
        first = fault.observed['firstFaults'][1]
        self.assertEqual((first['code'], first['location'], first['message']), ('TRANSFER_TIME_COMPONENT_UNANCHORED', '$.transfer.captureTime', self.ORPHAN_MESSAGE % ('source', self.ORPHAN_WHAT[kind], 'is')), name)
        self.assertEqual((first['observed']['side'], first['observed']['field']), ('source', 'captureTime'), name)
        self.assertFalse((self.tmp / name / 'photos').exists(), name)
        self.assertEqual(sorted(p.name for p in (self.tmp / name).glob('write-*')), [], name)       # no native write was ever started
        return first

    def test_E4H1_a_source_whose_offset_or_fraction_is_stated_only_by_a_carrier_without_its_own_time_is_refused_before_any_write_in_every_destination(self):
        for kind in ('o01', 'o02', 'o03', 'o04'):
            for destination in ('replace', 'timeless', 'blank'):
                self.assert_orphan_refused('h1-%s-%s' % (kind, destination), kind, destination, ['captureTime'])

    def test_E4H1_the_orphan_source_is_refused_in_a_mixed_selection_and_nothing_is_published(self):
        for kind in ('o01', 'o02', 'o03', 'o04'):
            for destination in ('replace', 'blank'):
                self.assert_orphan_refused('h1m-%s-%s' % (kind, destination), kind, destination, ['descriptive', 'captureTime'])

    def test_E4H1_an_orphan_exif_offset_names_its_carrier_and_value_in_the_refusal(self):
        first = self.assert_orphan_refused('h1d-o01', 'o01', 'replace', ['captureTime'])
        self.assertEqual(first['observed']['carriers'], [{'component': 'offset', 'family': 'exif', 'location': 'ExifIFD:0x9011', 'value': '+09:00'}])
        first = self.assert_orphan_refused('h1d-o03', 'o03', 'timeless', ['captureTime'])
        self.assertEqual(first['observed']['carriers'], [{'component': 'offset', 'family': 'iptc', 'location': '2:60', 'value': '+09:00'}])

    def test_E4H1_an_orphan_source_field_is_skipped_under_the_skip_field_policy_and_the_rest_of_the_mixed_selection_is_written(self):
        self.put('a.jpg', self.orphan_source('o03', mixed=True))
        self.put('b.jpg', self.timeless())
        try:
            result = self.run_op(self.doc(['descriptive', 'captureTime'], policies={'existing': 'replace', 'ambiguous': 'skipField'}), 'h1k')
        except SchemaxisError as error:
            self.fail('the orphan time field must be skipped and the title written, but the item was refused: %s' % [(x['code'], x['location']) for x in error.fault.observed['firstFaults']])
        self.assertEqual((result['written'], result['failed']), (1, 0))
        data = self.read('h1k', 'photos/b.jpg')
        self.assertEqual(snapshot(data, fields=['title'])['title']['value']['text'], 'Harbour')
        self.assertEqual(self.time_of(data), (None, None, None))                                       # the time was neither written nor invented
        decisions = {d['field']: (d['action'], d['reason']) for d in self.item('h1k')['decisions']}
        self.assertEqual(decisions['captureTime'], ('unchanged', 'sourceUnanchored'))
        self.assertEqual(self.verify('h1k')['nativeReplay'], 'fresh-replay-matched')

    def assert_orphan_admitted(self, name, kind, destination, groups, fraction):
        self.put('a.jpg', self.orphan_source(kind, mixed='descriptive' in groups))
        self.put('b.jpg', self.spread_destination(destination))
        result = self.written(groups, name)
        self.assertEqual((result['written'], result['failed']), (1, 0), name)
        data = self.read(name, 'photos/b.jpg')
        self.assertEqual(snapshot(data, fields=['captureTime'])['captureTime']['value'], {'local': '2024-03-01T10:20:30', 'offset': '+09:00', 'sub': fraction}, name)
        self.assertIn('captureTime', self.item(name)['proofs']['T']['nativeKeysCompared'], name)
        self.assertEqual(self.verify(name)['nativeReplay'], 'fresh-replay-matched', name)

    def test_E4H1_an_orphan_that_an_anchored_carrier_states_too_is_redundant_and_the_time_is_written_and_verified(self):
        for kind, fraction in (('o05', None), ('o06', '25')):
            for destination in ('replace', 'timeless', 'blank'):
                self.assert_orphan_admitted('h1r-%s-%s' % (kind, destination), kind, destination, ['captureTime'], fraction)
        self.assert_orphan_admitted('h1r-o05-mixed', 'o05', 'timeless', ['descriptive', 'captureTime'], None)

    def test_E4H1_an_iptc_time_with_its_own_date_is_anchored_and_still_written_and_verified(self):
        for destination in ('replace', 'timeless', 'blank'):
            self.assert_orphan_admitted('h1a-o07-%s' % destination, 'o07', destination, ['captureTime'], None)

    def test_E4H1_an_iptc_time_with_its_date_but_another_clock_than_the_exif_time_is_still_a_source_conflict(self):
        self.put('a.jpg', f.fx.jpeg(make='A', model='M', exif_version=b'0300', dto='2024:03:01 10:20:30', off=None, sub=None, iptc=[(2, 55, '20240301'), (2, 60, '235959+0900')]))
        self.put('b.jpg', self.spread_destination('replace'))
        fault = self.refuses(self.doc(['captureTime']), 'h1c', 'NO_USABLE_ITEMS')
        first = fault.observed['firstFaults'][1]
        self.assertEqual((first['code'], first['location']), ('TRANSFER_SOURCE_AMBIGUOUS', '$.transfer.captureTime'))
        self.assertEqual(sorted(p.name for p in (self.tmp / 'h1c').glob('write-*')), [])

    # a destination that already holds an orphan the write would leave in place
    DEST_MESSAGE = 'the destination capture time cannot be used: its UTC offset is stated only by a carrier that does not state the local time itself, so no association with that time is invented'

    def test_E4H1_a_destination_whose_offset_is_stated_only_by_an_iptc_time_without_its_date_is_refused_before_any_write(self):
        iptc_orphan = lambda clock, **kw: f.fx.jpeg(make='B', model='X', seed=2, exif_version=b'0300', **{**dict(dto=None, off=None, sub=None), **kw}, iptc=[(2, 60, clock)])
        for label, clock, kw in (('stale', '000000+0000', {}), ('same-offset', '102030+0900', {}), ('with-exif-time', '000000+0000', dict(dto='2020:01:01 00:00:00'))):
            name = 'h1x-' + label
            self.put('a.jpg', self.source(sub=None))
            self.put('b.jpg', iptc_orphan(clock, **kw))
            fault = self.refuses(self.doc(['captureTime']), name, 'NO_USABLE_ITEMS')
            first = fault.observed['firstFaults'][1]
            self.assertEqual((first['code'], first['location'], first['message']), ('TRANSFER_TIME_COMPONENT_UNANCHORED', 'captured/b.jpg', self.DEST_MESSAGE), name)
            self.assertEqual(first['observed']['side'], 'destination', name)
            self.assertFalse((self.tmp / name / 'photos').exists(), name)
            self.assertEqual(sorted(p.name for p in (self.tmp / name).glob('write-*')), [], name)

    def test_E4H1_a_destination_time_with_an_orphan_that_the_policy_keeps_is_not_refused_and_the_rest_of_the_selection_is_written(self):
        self.put('a.jpg', self.source(sub=None))
        self.put('b.jpg', f.fx.jpeg(make='B', model='X', seed=2, exif_version=b'0300', dto='2020:01:01 00:00:00', off=None, sub=None, iptc=[(2, 60, '000000+0000')]))
        result = self.run_op(self.doc(['descriptive', 'captureTime'], policies={'existing': 'keepDestination'}), 'h1z')
        self.assertEqual((result['written'], result['failed']), (1, 0))
        data = self.read('h1z', 'photos/b.jpg')
        self.assertEqual((snapshot(data, fields=['title'])['title']['value']['text'], self.time_of(data), self.iptc_time_of(data)), ('Harbour', ('2020:01:01 00:00:00', None, None), (None, '000000+0000')))
        self.assertEqual({d['field']: (d['action'], d['reason']) for d in self.item('h1z')['decisions']}['captureTime'], ('unchanged', 'keepDestination'))
        self.assertEqual(self.verify('h1z')['nativeReplay'], 'fresh-replay-matched')

    def test_E4H1_a_destination_with_an_orphan_exif_offset_or_fraction_that_the_write_replaces_is_still_written_and_verified(self):
        for name, dest, fraction in (('h1y-offset', self.timeless(off='+05:00'), '25'), ('h1y-fraction', self.timeless(sub='99'), '25')):
            self.put('a.jpg', self.source())
            self.put('b.jpg', dest)
            self.written(['captureTime'], name)
            data = self.read(name, 'photos/b.jpg')
            self.assertEqual(self.time_of(data), ('2024:03:01 10:20:30', '+09:00', fraction), name)
            self.assertEqual(self.verify(name)['nativeReplay'], 'fresh-replay-matched', name)

    def test_E4H1_the_native_listing_comparison_stays_independent_of_the_host_orphan_rule(self):
        # an orphan Exif offset or an IPTC time without its date is no capture time of the listing; the comparison neither calls the host reader nor adopts the orphan
        orphan_exif = {'EXIF:ExifIFD:OffsetTimeOriginal': ['+09:00']}
        self.assertIsNone(e4copy.native_time(orphan_exif))
        self.assertEqual(e4copy.native_time({**orphan_exif, 'XMP-exif:XMP-exif:DateTimeOriginal': ['2024:03:01 10:20:30']}), ('2024-03-01T10:20:30', None, None))
        self.assertEqual(e4copy.native_time({'EXIF:ExifIFD:DateTimeOriginal': ['2024:03:01 10:20:30'], 'IPTC:IPTC:TimeCreated': ['10:20:30+09:00']}), ('2024-03-01T10:20:30', None, None))


class OrphanTime(unittest.TestCase):
    """E4H-1, host only: the shared typed-snapshot rule. A capture-time offset or fraction that only a carrier without its own local time states (an Exif OffsetTimeOriginal or SubSecTimeOriginal
    without Exif DateTimeOriginal, an IPTC 2:60 without 2:55) is an orphan: the row of a PRESENT time is ``unsupported`` with the code ``TIME_COMPONENT_UNANCHORED``, never a composed value.
    Every expectation is a literal over a hand-built JPEG."""
    XMP = staticmethod(f.fx.xmp_properties)

    def row(self, **kw):
        return snapshot(f.fx.jpeg(make='A', model='M', exif_version=b'0300', **kw), fields=['captureTime'])['captureTime']

    def carriers(self, row):
        return [(c['component'], c['family'], c['location'], c['value']) for c in row.get('unanchored', [])]

    def test_an_exif_offset_without_an_exif_time_beside_an_xmp_local_time_is_unanchored(self):
        row = self.row(dto=None, off='+09:00', sub=None, xmp=self.XMP(exif_dto='2024-03-01T10:20:30'))
        self.assertEqual((row['state'], row.get('code'), 'value' in row), ('unsupported', 'TIME_COMPONENT_UNANCHORED', False))
        self.assertEqual(self.carriers(row), [('offset', 'exif', 'ExifIFD:0x9011', '+09:00')])

    def test_an_exif_fraction_without_an_exif_time_beside_an_xmp_photoshop_time_is_unanchored(self):
        row = self.row(dto=None, off=None, sub='25', xmp=self.XMP(captured='2024-03-01T10:20:30+09:00'))
        self.assertEqual((row['state'], row.get('code')), ('unsupported', 'TIME_COMPONENT_UNANCHORED'))
        self.assertEqual(self.carriers(row), [('sub', 'exif', 'ExifIFD:0x9291', '25')])

    def test_an_iptc_time_without_its_date_is_unanchored_whatever_its_clock_states(self):
        for clock in ('102030+0900', '235959+0900'):
            row = self.row(dto='2024:03:01 10:20:30', off=None, sub=None, iptc=[(2, 60, clock)])
            self.assertEqual((row['state'], row.get('code')), ('unsupported', 'TIME_COMPONENT_UNANCHORED'), clock)
            self.assertEqual(self.carriers(row), [('offset', 'iptc', '2:60', '+09:00')], clock)

    def test_both_components_orphaned_are_listed_in_catalogue_order(self):
        row = self.row(dto=None, off='+09:00', sub='25', xmp=self.XMP(exif_dto='2024-03-01T10:20:30'))
        self.assertEqual((row['state'], self.carriers(row)), ('unsupported', [('offset', 'exif', 'ExifIFD:0x9011', '+09:00'), ('sub', 'exif', 'ExifIFD:0x9291', '25')]))

    def test_an_orphan_that_an_anchored_carrier_states_too_is_redundant_and_the_time_is_present(self):
        row = self.row(dto=None, off='+09:00', sub=None, xmp=self.XMP(captured='2024-03-01T10:20:30+09:00'))
        self.assertEqual((row['state'], row.get('value'), 'unanchored' in row), ('present', {'local': '2024-03-01T10:20:30', 'offset': '+09:00', 'sub': None}, False))
        row = self.row(dto=None, off=None, sub='25', xmp=self.XMP(exif_dto='2024-03-01T10:20:30.25+09:00'))
        self.assertEqual((row['state'], row.get('value')), ('present', {'local': '2024-03-01T10:20:30', 'offset': '+09:00', 'sub': '25'}))

    def test_one_orphaned_component_among_anchored_ones_still_makes_the_time_unsupported(self):
        row = self.row(dto=None, off=None, sub='25', xmp=self.XMP(captured='2024-03-01T10:20:30+09:00'))        # the offset is anchored (XMP), the fraction is not
        self.assertEqual((row['state'], self.carriers(row)), ('unsupported', [('sub', 'exif', 'ExifIFD:0x9291', '25')]))

    def test_anchored_carriers_are_unchanged(self):
        exif = self.row(dto='2024:03:01 10:20:30', off='+09:00', sub='25')
        iptc = self.row(dto=None, off=None, sub=None, iptc=[(2, 55, '20240301'), (2, 60, '102030+0900')])
        bare = self.row(dto='2024:03:01 10:20:30', off=None, sub=None)
        self.assertEqual([(r['state'], r.get('value')) for r in (exif, iptc, bare)],
                         [('present', {'local': '2024-03-01T10:20:30', 'offset': '+09:00', 'sub': '25'}), ('present', {'local': '2024-03-01T10:20:30', 'offset': '+09:00', 'sub': None}),
                          ('present', {'local': '2024-03-01T10:20:30', 'offset': None, 'sub': None})])

    def test_orphans_alone_state_no_time_and_a_time_with_disagreeing_clocks_stays_ambiguous(self):
        alone = self.row(dto=None, off='+09:00', sub=None)
        self.assertEqual((alone['state'], self.carriers(alone)), ('absent', [('offset', 'exif', 'ExifIFD:0x9011', '+09:00')]))
        clash = self.row(dto='2024:03:01 10:20:30', off=None, sub=None, iptc=[(2, 55, '20240301'), (2, 60, '235959+0900')])
        self.assertEqual((clash['state'], 'unanchored' in clash), ('ambiguous', False))

    def test_the_naming_time_sources_carry_the_same_orphans(self):
        from schemaxis.adaptors.exiftool import containers, e4host, records
        data = f.fx.jpeg(dto='2024:03:01 10:20:30', off=None, sub=None, iptc=[(2, 60, '102030+0900')])
        record = records.Record(records.Payloads(containers.locate(data)), e4model.VIEW)
        fields = {name: record.field(name) for name in ('capturedLocalE3', 'capturedOffsetE3', 'capturedSubSecondE3')}
        aggregate = e4host.time_sources(fields)['aggregate']
        self.assertEqual((aggregate['local'], aggregate['offset'], aggregate.get('unanchored')), ('2024-03-01T10:20:30', '+09:00', [{'component': 'offset', 'family': 'iptc', 'location': '2:60', 'value': '+09:00'}]))
        anchored = records.Record(records.Payloads(containers.locate(f.fx.jpeg(dto='2024:03:01 10:20:30', off='+09:00', sub=None))), e4model.VIEW)
        self.assertNotIn('unanchored', e4host.time_sources({name: anchored.field(name) for name in fields})['aggregate'])

    def test_the_sidecar_model_refuses_the_orphan_and_skips_it_under_the_skip_field_policy(self):
        row = self.row(dto='2024:03:01 10:20:30', off=None, sub=None, iptc=[(2, 60, '102030+0900')])
        model, losses, infos, faults, skipped = e4model.sidecar_model({'captureTime': row}, ['captureTime'], {'ambiguous': 'refuseItem'})
        self.assertEqual((model, [(x['code'], x['field']) for x in faults], skipped), ({}, [('TRANSFER_TIME_COMPONENT_UNANCHORED', 'captureTime')], []))
        self.assertEqual([x['message'] for x in faults], ['the source capture time cannot be used: its UTC offset is stated only by a carrier that does not state the local time itself, so no association with that time is invented'])
        model, losses, infos, faults, skipped = e4model.sidecar_model({'captureTime': row}, ['captureTime'], {'ambiguous': 'skipField'})
        self.assertEqual((model, faults, [(x['field'], x['reason']) for x in skipped]), ({}, [], [('captureTime', 'unanchored')]))


class NativeTimeCarrier(unittest.TestCase):
    """E4F-1, host only: the fixed-listing capture time ``native_time`` reads, from hand-written listings spelled as ExifTool 13.55 lists them (``IPTC:DateCreated`` ``2024:03:01``,
    ``IPTC:TimeCreated`` ``10:20:30+09:00`` with the offset optional), and the T-native comparison of two such listings. Every expectation is a literal."""
    IPTC = {'IPTC:IPTC:DateCreated': ['2024:03:01'], 'IPTC:IPTC:TimeCreated': ['10:20:30+09:00']}
    EXIF = {'EXIF:ExifIFD:DateTimeOriginal': ['2024:03:01 10:20:30'], 'EXIF:ExifIFD:OffsetTimeOriginal': ['+09:00'], 'EXIF:ExifIFD:SubSecTimeOriginal': ['25']}
    SOURCE = ('2024-03-01T10:20:30', '+09:00', None)

    def test_an_iptc_date_with_its_time_and_offset_is_the_capture_time_the_listing_states(self):
        self.assertEqual(e4copy.native_time(self.IPTC), self.SOURCE)

    def test_an_iptc_time_without_an_offset_or_with_a_zero_negative_or_fractional_offset_is_read_as_stated(self):
        for time, expected in (('10:20:30', ('2024-03-01T10:20:30', None, None)), ('10:20:30+00:00', ('2024-03-01T10:20:30', '+00:00', None)),
                               ('10:20:30-05:30', ('2024-03-01T10:20:30', '-05:30', None)), ('10:20:30.25+09:00', ('2024-03-01T10:20:30', '+09:00', '25'))):
            self.assertEqual(e4copy.native_time({**self.IPTC, 'IPTC:IPTC:TimeCreated': [time]}), expected, time)

    def test_an_iptc_date_without_a_time_or_a_time_without_a_date_is_no_capture_time(self):
        self.assertIsNone(e4copy.native_time({'IPTC:IPTC:DateCreated': ['2024:03:01']}))
        self.assertIsNone(e4copy.native_time({'IPTC:IPTC:TimeCreated': ['10:20:30+09:00']}))
        self.assertIsNone(e4copy.native_time({}))

    def test_an_unreadable_iptc_pair_is_compared_as_the_listed_text_never_dropped(self):
        self.assertEqual(e4copy.native_time({'IPTC:IPTC:DateCreated': ['2024:03:01'], 'IPTC:IPTC:TimeCreated': ['noon']}), ('2024:03:01 noon', None, None))

    def test_carriers_that_state_the_same_time_are_one_capture_time_each_stating_what_it_states(self):
        self.assertEqual(e4copy.native_time({**self.IPTC, **self.EXIF}), ('2024-03-01T10:20:30', '+09:00', '25'))
        xmp = {'XMP-exif:XMP-exif:DateTimeOriginal': ['2024:03:01 10:20:30.25+09:00']}
        self.assertEqual(e4copy.native_time({**self.IPTC, **xmp}), ('2024-03-01T10:20:30', '+09:00', '25'))
        self.assertEqual(e4copy.native_time({**self.IPTC, 'XMP-photoshop:XMP-photoshop:DateCreated': ['2024:03:01 10:20:30+09:00']}), ('2024-03-01T10:20:30', '+09:00', None))
        self.assertEqual(e4copy.native_time({'IPTC:IPTC:DateCreated': ['2024:03:01'], 'IPTC:IPTC:TimeCreated': ['10:20:30'], 'XMP-photoshop:XMP-photoshop:DateCreated': ['2024:03:01 10:20:30Z']}),
                         ('2024-03-01T10:20:30', '+00:00', None))                          # a Z offset is +00:00, the one the host reader also gives it

    # E4G-1: a capture time that the source spreads over carriers (the Exif local time, the offset or the fraction in another carrier) is ONE capture time with every component any carrier states
    EXIF_BARE = {'EXIF:ExifIFD:DateTimeOriginal': ['2024:03:01 10:20:30']}
    PHOTOSHOP = {'XMP-photoshop:XMP-photoshop:DateCreated': ['2024:03:01 10:20:30+09:00']}
    XMP_EXIF = {'XMP-exif:XMP-exif:DateTimeOriginal': ['2024:03:01 10:20:30.25+09:00']}

    def test_an_exif_time_without_an_offset_takes_the_offset_that_iptc_or_xmp_states_for_the_same_time(self):
        for label, other in (('iptc', self.IPTC), ('photoshop', self.PHOTOSHOP)):
            self.assertEqual(e4copy.native_time({**self.EXIF_BARE, **other}), ('2024-03-01T10:20:30', '+09:00', None), label)

    def test_an_exif_time_without_an_offset_or_a_fraction_takes_both_from_the_xmp_exif_date(self):
        self.assertEqual(e4copy.native_time({**self.EXIF_BARE, **self.XMP_EXIF}), ('2024-03-01T10:20:30', '+09:00', '25'))

    def test_the_offset_and_the_fraction_may_each_come_from_a_different_carrier(self):
        exif = {**self.EXIF_BARE, 'EXIF:ExifIFD:SubSecTimeOriginal': ['25']}
        self.assertEqual(e4copy.native_time({**exif, **self.IPTC}), ('2024-03-01T10:20:30', '+09:00', '25'))
        exif = {**self.EXIF_BARE, 'EXIF:ExifIFD:OffsetTimeOriginal': ['+09:00']}
        self.assertEqual(e4copy.native_time({**exif, **self.XMP_EXIF}), ('2024-03-01T10:20:30', '+09:00', '25'))

    def test_a_component_no_carrier_states_stays_unstated_and_no_zone_or_fraction_is_invented(self):
        self.assertEqual(e4copy.native_time(self.EXIF_BARE), ('2024-03-01T10:20:30', None, None))
        self.assertEqual(e4copy.native_time({**self.EXIF_BARE, 'IPTC:IPTC:DateCreated': ['2024:03:01'], 'IPTC:IPTC:TimeCreated': ['10:20:30']}), ('2024-03-01T10:20:30', None, None))

    def test_carriers_that_disagree_on_a_component_leave_that_component_conflicting_never_the_first_carriers_value(self):
        self.assertEqual(e4copy.native_time({**self.EXIF, **{'IPTC:IPTC:TimeCreated': ['10:20:30+08:00'], 'IPTC:IPTC:DateCreated': ['2024:03:01']}}), ('2024-03-01T10:20:30', ('+08:00', '+09:00'), '25'))
        self.assertEqual(e4copy.native_time({**self.EXIF, **self.XMP_EXIF, 'EXIF:ExifIFD:SubSecTimeOriginal': ['26']}), ('2024-03-01T10:20:30', '+09:00', ('25', '26')))
        self.assertEqual(e4copy.native_time({**self.EXIF_BARE, **{'XMP-photoshop:XMP-photoshop:DateCreated': ['2024:03:01 10:20:31+09:00']}}), (('2024-03-01T10:20:30', '2024-03-01T10:20:31'), '+09:00', None))
        self.assertEqual(e4copy.native_time({**self.EXIF_BARE, **{'XMP-photoshop:XMP-photoshop:DateCreated': ['2024:03:01 10:20:30Z'], 'XMP-exif:XMP-exif:DateTimeOriginal': ['2024:03:01 10:20:30+00:00']}}),
                         ('2024-03-01T10:20:30', '+00:00', None))                          # Z and +00:00 are the same stated offset

    def compare(self, source, output):
        return e4copy.native_e3_problems('captureTime', source, output, '$.items[1]')[0]

    def test_a_time_the_source_states_in_exif_equals_the_time_the_output_states_in_iptc(self):
        self.assertEqual(self.compare({k: v for k, v in self.EXIF.items() if 'SubSec' not in k}, self.IPTC), [])
        self.assertEqual(self.compare(self.IPTC, self.IPTC), [])

    def test_a_changed_iptc_output_time_is_a_mismatch_with_the_typed_source_and_output(self):
        for time in ('10:20:31+09:00', '10:20:30+08:00', '10:20:30'):
            problems = self.compare(self.IPTC, {**self.IPTC, 'IPTC:IPTC:TimeCreated': [time]})
            self.assertEqual([(p['code'], p['location']) for p in problems], [('TRANSFER_READBACK_MISMATCH', '$.items[1].native')], time)
            self.assertEqual(problems[0]['source'], list(self.SOURCE), time)
        problems = self.compare(self.IPTC, {**self.IPTC, 'IPTC:IPTC:DateCreated': ['2024:03:02']})
        self.assertEqual(problems[0]['output'], ['2024-03-02T10:20:30', '+09:00', None])

    def test_an_output_without_any_capture_time_is_a_mismatch_and_a_source_without_one_is_not_compared(self):
        problems = self.compare(self.IPTC, {'IPTC:IPTC:DateCreated': ['2024:03:01']})
        self.assertEqual([(p['location'], p['output']) for p in problems], [('$.items[1].native', None)])
        self.assertEqual(self.compare({}, self.IPTC), [])


    def mismatch(self, source, output):
        problems = self.compare(source, output)
        self.assertEqual([(p['code'], p['location']) for p in problems], [('TRANSFER_READBACK_MISMATCH', '$.items[1].native')])
        return problems[0]

    SPREAD_OFFSET = {**EXIF_BARE, **IPTC}                       # the Exif time without an offset, the offset in IPTC
    OUTPUT_EXIF = {**EXIF_BARE, 'EXIF:ExifIFD:OffsetTimeOriginal': ['+09:00']}

    def test_E4G1_a_correct_output_of_a_spread_source_states_the_composed_time_and_is_not_a_mismatch(self):
        self.assertEqual(self.compare(self.SPREAD_OFFSET, self.OUTPUT_EXIF), [])                             # the offset the source states in IPTC is the one the output states in Exif
        self.assertEqual(self.compare(self.SPREAD_OFFSET, self.IPTC), [])
        self.assertEqual(self.compare({**self.EXIF_BARE, **self.PHOTOSHOP}, self.OUTPUT_EXIF), [])
        self.assertEqual(self.compare({**self.EXIF_BARE, **self.XMP_EXIF}, {**self.OUTPUT_EXIF, 'EXIF:ExifIFD:SubSecTimeOriginal': ['25']}), [])
        self.assertEqual(self.compare({**self.EXIF, **self.IPTC}, self.EXIF), [])                              # carriers that agree stay a green control

    def test_E4G1_an_output_with_another_offset_or_fraction_or_second_than_the_composed_source_is_a_mismatch_with_the_typed_values(self):
        wrong = self.mismatch(self.SPREAD_OFFSET, {**self.EXIF_BARE, 'EXIF:ExifIFD:OffsetTimeOriginal': ['+08:00']})
        self.assertEqual((wrong['source'], wrong['output']), (['2024-03-01T10:20:30', '+09:00', None], ['2024-03-01T10:20:30', '+08:00', None]))
        wrong = self.mismatch({**self.EXIF_BARE, **self.XMP_EXIF}, {**self.OUTPUT_EXIF, 'EXIF:ExifIFD:SubSecTimeOriginal': ['26']})
        self.assertEqual((wrong['source'], wrong['output']), (['2024-03-01T10:20:30', '+09:00', '25'], ['2024-03-01T10:20:30', '+09:00', '26']))
        self.mismatch(self.SPREAD_OFFSET, {**self.OUTPUT_EXIF, 'EXIF:ExifIFD:DateTimeOriginal': ['2024:03:01 10:20:31']})

    def test_E4G1_an_output_that_drops_a_component_the_source_states_in_any_carrier_is_a_mismatch_never_accepted_as_unstated(self):
        self.mismatch(self.SPREAD_OFFSET, self.EXIF_BARE)                                                    # the offset the source states in IPTC is lost
        self.mismatch({**self.EXIF_BARE, **self.XMP_EXIF}, self.OUTPUT_EXIF)                                 # the fraction is lost
        self.mismatch({**self.EXIF_BARE, **self.PHOTOSHOP}, {'IPTC:IPTC:DateCreated': ['2024:03:01'], 'IPTC:IPTC:TimeCreated': ['10:20:30']})
        self.mismatch(self.SPREAD_OFFSET, {'XMP-photoshop:XMP-photoshop:DateCreated': ['2024:03:01 10:20:30']})                  # an XMP date without the offset
        problem = self.mismatch({**self.EXIF_BARE, **self.PHOTOSHOP}, {**self.OUTPUT_EXIF, 'EXIF:ExifIFD:SubSecTimeOriginal': ['25']})        # a fraction the source never stated is not invented
        self.assertEqual(problem['output'], ['2024-03-01T10:20:30', '+09:00', '25'])

    def test_E4G1_a_source_or_an_output_whose_carriers_disagree_is_a_mismatch_even_when_both_sides_disagree_alike(self):
        torn = {**self.EXIF, 'IPTC:IPTC:DateCreated': ['2024:03:01'], 'IPTC:IPTC:TimeCreated': ['10:20:30+08:00']}
        self.assertEqual(self.mismatch(torn, torn)['source'], ['2024-03-01T10:20:30', ['+08:00', '+09:00'], '25'])
        self.mismatch(self.SPREAD_OFFSET, torn)
        self.mismatch(torn, self.SPREAD_OFFSET)


class XmpAbsentComponent(unittest.TestCase):
    """E4F-2, host only: ``written_xmp_absent_component`` waives exactly the typed code of a component that a freshly written XMP date lacks, and nothing wider. The XMP dates are hand-built
    in the fixtures; every expectation is a literal."""
    AT = '$.items[1]'
    LOCAL = 'capturedLocalE3'
    SUB = 'capturedSubSecondE3'
    OFFSET = 'capturedOffsetE3'

    def xmp_capture(self, captured):
        return f.fx.jpeg(exif=False, xmp=f.fx.xmp_properties(exif_dto=captured), seed=3) if captured else f.fx.jpeg(exif=False, xmp=None, seed=3)

    def item(self, data):
        from schemaxis.adaptors.exiftool import containers, e3read, e3write, records
        reader = records.Record(records.Payloads(containers.locate(data)), e3write.VIEW)
        return {'e3fields': {name: reader.field(name) for name in e3read.field_names('reconcileTime')}}

    def payloads(self, data):
        from schemaxis.adaptors.exiftool import containers, records
        return records.Payloads(containers.locate(data))

    def problem(self, name, **kw):
        return {**{'code': 'READBACK_MISMATCH', 'message': 'a time source the plan leaves alone changed', 'location': '%s.fields.%s.xmp' % (self.AT, name), 'source': 'exif:DateTimeOriginal'}, **kw}

    PLAN = {'expect': {('capturedLocalE3', 'xmp', 'exif:DateTimeOriginal'): '2024-03-01T10:20:30', ('capturedOffsetE3', 'xmp', 'exif:DateTimeOriginal'): '+09:00'}}

    def waived(self, found, before, after, plan=None):
        return e4copy.written_xmp_absent_component(found, plan or self.PLAN, self.item(before), self.payloads(after), self.AT)

    def test_the_typed_no_fraction_code_of_an_xmp_date_the_plan_wrote_is_waived(self):
        self.assertTrue(self.waived(self.problem(self.SUB), self.xmp_capture(None), self.xmp_capture('2024-03-01T10:20:30+09:00')))

    def test_the_typed_no_offset_code_of_an_xmp_date_the_plan_wrote_without_an_offset_is_waived(self):
        plan = {'expect': {('capturedLocalE3', 'xmp', 'exif:DateTimeOriginal'): '2024-03-01T10:20:30'}}
        self.assertTrue(self.waived(self.problem(self.OFFSET), self.xmp_capture(None), self.xmp_capture('2024-03-01T10:20:30.25'), plan))

    def test_a_fraction_that_vanished_or_is_present_or_an_unwritten_date_or_another_problem_is_not_waived(self):
        blank, written = self.xmp_capture(None), self.xmp_capture('2024-03-01T10:20:30+09:00')
        self.assertFalse(self.waived(self.problem(self.SUB), self.xmp_capture('2024-03-01T10:20:30.25+09:00'), written))        # the fraction was there before and is gone
        self.assertFalse(self.waived(self.problem(self.SUB), blank, self.xmp_capture('2024-03-01T10:20:30.25+09:00')))        # the fraction is present after: not the absent code
        self.assertFalse(self.waived(self.problem(self.SUB), self.xmp_capture('2024-03-01T10:20:30+09:00'), written))         # the date existed before: the plan wrote no date here
        self.assertFalse(self.waived(self.problem(self.SUB), blank, written, {'expect': {}}))                                  # the plan did not write the XMP date
        self.assertFalse(self.waived(self.problem(self.SUB), blank, written, {'expect': {**self.PLAN['expect'], ('capturedSubSecondE3', 'xmp', 'exif:DateTimeOriginal'): '25'}}))     # the plan expected a fraction
        self.assertFalse(self.waived(self.problem(self.SUB, message='a written time component does not read back as planned'), blank, written))
        self.assertFalse(self.waived(self.problem(self.SUB, location='%s.fields.%s.exif' % (self.AT, self.SUB)), blank, written))
        self.assertFalse(self.waived(self.problem(self.SUB, source='photoshop:DateCreated'), blank, written))


if __name__ == '__main__':
    unittest.main()
