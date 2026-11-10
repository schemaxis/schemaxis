"""E4 exportSidecar: hand-literal host cases of the serializer, the altitude and coordinate rules (S-1..S-7, S-12..S-14) and native runs against ExifTool 13.55.

Every expected byte, key and number below is a literal written from the contract and its amendments (AM7-AM11); none is computed by the serializer or by ExifTool.
"""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT / 'tests/unit')]

import exiftool_e4_fixtures as f  # noqa: E402
from exiftool_e4_fixtures import V, master, plain  # noqa: E402
from schemaxis.adaptors.exiftool import e4model, xmp, xmpwrite  # noqa: E402

EXPECTED_S1 = ('<?xpacket begin="﻿" id="W5M0MpCehiHzreSzNTczkc9d"?>\n<x:xmpmeta xmlns:x="adobe:ns:meta/">\n<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">\n'
               '<rdf:Description rdf:about=""\n   xmlns:dc="http://purl.org/dc/elements/1.1/">\n'
               '  <dc:title><rdf:Alt><rdf:li xml:lang="x-default">Harbour</rdf:li><rdf:li xml:lang="de-DE">Hafen</rdf:li></rdf:Alt></dc:title>\n'
               '  <dc:rights><rdf:Alt><rdf:li xml:lang="x-default">(c) 2024 A</rdf:li></rdf:Alt></dc:rights>\n'
               '  <dc:subject><rdf:Bag><rdf:li>k1</rdf:li><rdf:li>k2</rdf:li></rdf:Bag></dc:subject>\n'
               '  <dc:creator><rdf:Seq><rdf:li>Ann; Bob</rdf:li><rdf:li>Cy</rdf:li></rdf:Seq></dc:creator>\n'
               '</rdf:Description>\n</rdf:RDF>\n</x:xmpmeta>\n<?xpacket end="w"?>\n').encode('utf-8')


class Serializer(unittest.TestCase):
    def test_S1_the_closed_serializer_output_equals_a_byte_literal(self):
        model = {'title': {'text': 'Harbour', 'languages': [{'language': 'de-DE', 'text': 'Hafen'}]}, 'copyright': {'text': '(c) 2024 A', 'languages': []}, 'keywords': ['k1', 'k2'], 'creator': ['Ann; Bob', 'Cy']}
        self.assertEqual(xmpwrite.build(model), EXPECTED_S1)

    def test_S2_markup_characters_are_escaped_and_nfd_text_is_kept_exactly(self):
        data = xmpwrite.build({'title': {'text': 'é <&>"\' \U0001f600', 'languages': []}})
        self.assertIn('<rdf:li xml:lang="x-default">é &lt;&amp;&gt;&quot;&apos; \U0001f600</rdf:li>'.encode('utf-8'), data)
        self.assertEqual(xmp.parse(data)['dc:title'][0]['value']['x-default'], 'é <&>"\' \U0001f600')

    def test_S3_a_character_xml_cannot_carry_is_refused_never_stripped(self):
        with self.assertRaises(xmpwrite.SidecarError) as raised:
            xmpwrite.build({'title': {'text': 'a\x01b', 'languages': []}})
        self.assertEqual((raised.exception.code, raised.exception.observed['codePoint']), ('SIDECAR_TEXT_NOT_XML', 'U+0001'))

    def test_S4_S5_the_altitude_references_follow_exif3_and_the_height_reference(self):
        sea = {'state': 'present', 'reference': 'seaLevel', 'signKnown': True, 'meters': '-12.5', 'stored': [25, 2]}
        self.assertEqual(e4model.altitude_model(sea, 'omitUnlessReferenceKnown')[0], {'gpsAltitude': (25, 2), 'gpsAltitudeRef': 3})
        ellipsoid = {'state': 'present', 'reference': 'ellipsoidal', 'signKnown': True, 'meters': '52.317', 'stored': [52317, 1000]}
        self.assertEqual(e4model.altitude_model(ellipsoid, 'omitUnlessReferenceKnown')[0], {'gpsAltitude': (52317, 1000), 'gpsAltitudeRef': 0})
        below = dict(ellipsoid, meters='-52.317')
        self.assertEqual(e4model.altitude_model(below, 'omitUnlessReferenceKnown')[0]['gpsAltitudeRef'], 1)

    def test_S4b_code_two_carries_the_misread_residual_and_codes_one_and_three_an_info(self):
        high = {'state': 'present', 'reference': 'seaLevel', 'signKnown': True, 'meters': '52.317', 'stored': [52317, 1000]}
        entries, losses, infos = e4model.altitude_model(high, 'omitUnlessReferenceKnown')
        self.assertEqual(entries['gpsAltitudeRef'], 2)
        self.assertEqual([x['code'] for x in losses], ['altitudeRefMisreadByExifTool13_55Composite'])
        self.assertEqual(infos, [])
        entries, losses, infos = e4model.altitude_model(dict(high, meters='-52.317'), 'omitUnlessReferenceKnown')
        self.assertEqual((entries['gpsAltitudeRef'], losses, [x['code'] for x in infos]), (3, [], ['exifToolCompositeLabelsSeaLevel']))

    def test_S6_an_unspecified_legacy_reference_omits_the_altitude_or_refuses_by_policy(self):
        legacy = {'state': 'present', 'reference': 'unspecified', 'signKnown': True, 'meters': '12.5', 'stored': [25, 2]}
        entries, losses, _ = e4model.altitude_model(legacy, 'omitUnlessReferenceKnown')
        self.assertEqual((entries, [x['code'] for x in losses]), ({}, ['altitudeReferenceUnspecified']))
        entries, losses, _ = e4model.altitude_model(legacy, 'refuseUnlessReferenceKnown')
        self.assertEqual((entries, losses[0]['code']), (None, 'ALTITUDE_REFERENCE_UNSPECIFIED'))

    def test_S7_coordinate_forms_and_the_stated_quantisation_are_exact(self):
        cases = [([(35, 1), (7, 1), (60, 1)], 'N', '35,8.0N', 0.0), ([(35, 1), (7, 1), (24, 1)], 'N', '35,7,24N', None),
                 ([(35, 1), (7, 1), (671611, 27475)], 'N', '35,7.40740734N', 3.640e-10), ([(179, 1), (59, 1), (83335, 1389)], 'E', '179,59.99994E', 2.880e-07)]
        for components, ref, literal, difference in cases:
            found, quantisation = xmpwrite.coordinate_literal(components, ref)
            self.assertEqual(found, literal)
            if difference is None:
                self.assertIsNone(quantisation)
            else:
                self.assertAlmostEqual(quantisation['differenceArcSeconds'], difference, delta=difference * 0.01 + 1e-15)

    def test_S12_the_bound_is_one_mebibyte(self):
        ok = xmpwrite.build({'keywords': ['k' * 63 + str(i % 10) for i in range(2000)]})
        self.assertLess(len(ok), xmpwrite.MAX_BYTES)
        with self.assertRaises(xmpwrite.SidecarError) as raised:
            xmpwrite.build({'keywords': ['k' * 63 + str(i % 10) for i in range(20000)]})
        self.assertEqual(raised.exception.code, 'SIDECAR_BOUND')

    def test_S13_S14_the_native_comparison_texts_of_rationals_are_fifteen_significant_digits(self):
        from schemaxis.adaptors.exiftool import codecs
        self.assertEqual([codecs.native_float_text(p) for p in ((10, 30), (-1, 3), (35, 2), (28, 10))], ['0.333333333333333', '-0.333333333333333', '17.5', '2.8'])

    def test_S4c_a_listing_with_a_composite_key_is_rejected_and_the_fixed_listing_carries_no_composite_dependency(self):
        from schemaxis.adaptors.exiftool import e4host, listing
        self.assertIn('-e', listing.FIXED)
        record = {'fault': None, 'errors': [], 'warnings': [], 'observations': [{'group0': 'Composite', 'group1': 'Composite', 'name': 'GPSAltitude', 'instance': 0, 'value': '-12.5'}]}
        problems = e4host.native_problems({'gpsAltitude': (25, 2), 'gpsAltitudeRef': 2}, record)
        self.assertEqual(len(problems), 1)
        self.assertIn('Composite', problems[0]['message'])

    def test_AM7_the_property_to_native_key_map_has_29_distinct_properties_with_the_pinned_renames(self):
        self.assertEqual(len(xmpwrite.PROPERTIES), 29)
        self.assertEqual(len(set(xmpwrite.PROPERTIES)), 29)
        self.assertEqual(xmpwrite.NATIVE['exif:ExposureBiasValue'], 'XMP-exif:ExposureCompensation')
        self.assertEqual(xmpwrite.NATIVE['exif:FocalLengthIn35mmFilm'], 'XMP-exif:FocalLengthIn35mmFormat')
        self.assertEqual(xmpwrite.NATIVE['exifEX:BodySerialNumber'], 'XMP-exifEX:SerialNumber')
        self.assertEqual(xmpwrite.NATIVE['exif:GPSTimeStamp'], 'XMP-exif:GPSDateTime')

    def test_the_published_property_names_are_the_exact_closed_set(self):
        self.assertEqual(sorted(xmpwrite.PROPERTIES), sorted(['dc:title', 'dc:description', 'dc:rights', 'dc:subject', 'dc:creator', 'xmpRights:WebStatement', 'xmp:Rating', 'photoshop:City', 'photoshop:Country',
                                                              'photoshop:DateCreated', 'tiff:Make', 'tiff:Model', 'exifEX:LensMake', 'exifEX:LensModel', 'exifEX:BodySerialNumber', 'exifEX:LensSerialNumber',
                                                              'exif:ExposureTime', 'exif:FNumber', 'exif:FocalLength', 'exif:ExposureBiasValue', 'exif:FocalLengthIn35mmFilm', 'exifEX:PhotographicSensitivity',
                                                              'exif:DateTimeOriginal', 'exif:GPSLatitude', 'exif:GPSLongitude', 'exif:GPSAltitude', 'exifEX:GPSAltitudeRef', 'exif:GPSMapDatum', 'exif:GPSTimeStamp']))


class Native(f.NativeCase):
    def export(self, name='export', groups=('descriptive', 'rights', 'camera', 'exposure', 'deviceSerials'), **policies):
        self.put('a.jpg', master())
        doc = {'version': V, 'operation': 'exportSidecar', 'media': self.items('a'), 'transfer': {'groups': list(groups)}}
        if policies:
            doc['policies'] = policies
        return self.run_op(doc, name)

    def test_S1_native_export_writes_the_planned_values_and_every_property_is_anchored(self):
        result = self.export()
        self.assertEqual((result['written'], result['proofs']), (1, ['serializer', 'readerReread', 'nativeAnchor']))
        parsed = xmp.parse(self.read('export', 'sidecars/a.xmp'))
        self.assertEqual(parsed['dc:title'][0]['value'], {'x-default': 'Harbour', 'de-DE': 'Hafen'})
        self.assertEqual(parsed['dc:subject'][0]['value'], ['k1', 'k2'])
        self.assertEqual(parsed['dc:creator'][0], {'kind': 'list', 'container': 'Seq', 'value': ['Ann; Bob', 'Cy']})
        self.assertEqual(parsed['exif:ExposureTime'][0]['value'], '10/30')
        self.assertEqual(parsed['exif:ExposureBiasValue'][0]['value'], '-2/6')
        self.assertEqual(parsed['exifEX:BodySerialNumber'][0]['value'], 'B123')
        self.assertEqual(parsed['exifEX:PhotographicSensitivity'][0]['value'], '400')
        self.assertEqual(len(parsed), 16)
        report = self.json('export', 'sidecar-report.json')
        self.assertEqual(report['items'][0]['proofs']['S'], {'nativeAnchored': True, 'nativeKeys': report['items'][0]['proofs']['S']['nativeKeys'], 'reread': True, 'reproduced': True})
        self.assertIn('XMP-exif:ExposureCompensation', report['items'][0]['proofs']['S']['nativeKeys'])
        self.assertEqual(self.verify('export')['nativeReplay'], 'fresh-replay-matched')
        self.record('test_exiftool_e4_sidecar.Native.S1', 'exportSidecar', 'supported', supported=True, outcome='succeeded', independentlyVerified=True)

    def test_S10_every_group_exports_all_29_properties_and_native_lists_exactly_the_mapped_keys(self):
        xmp_props = (f.lang_alt('dc:title', 'Harbour', de_DE='Hafen') + f.lang_alt('dc:description', 'A quiet harbour') + f.bag('dc:subject', 'k1', 'k2') + f.bag('dc:creator', 'Ann', kind='Seq')
                     + f.lang_alt('dc:rights', '(c) 2026 A') + '<xmpRights:WebStatement>https://example.org/r</xmpRights:WebStatement><xmp:Rating>4</xmp:Rating>'
                     + '<photoshop:City>Kyoto</photoshop:City><photoshop:Country>Japan</photoshop:Country>')
        exif_extra = [f.rational(0x829A, 10, 30), f.rational(0x829D, 28, 10), f.a.short_entry(f.O, 0x8827, 400), f.rational(0x920A, 35, 2), f.a.short_entry(f.O, 0xA405, 52), f.srational(0x9204, -2, 6),
                      f.a.ascii_entry(0xA433, 'LensCo'), f.a.ascii_entry(0xA434, 'L50'), f.a.ascii_entry(0xA435, 'L456')]
        gps = {'version': (2, 4, 0, 0), 'lat': [(35, 1), (7, 1), (24, 1)], 'lat_ref': 'N', 'lon': [(139, 1), (45, 1), (36, 1)], 'lon_ref': 'W', 'alt': (25, 2), 'alt_ref': 3, 'datum': 'WGS-84',
               'date': '2026:03:01', 'time': [(11, 1), (0, 1), (0, 1)]}
        self.put('a.jpg', f.fx.full_time(make='Canon', model='EOS 5D', serial='B123', exif_version=b'0300', exif_extra=exif_extra, gps=gps,
                                         xmp=f.fx.xmp_properties(captured='2026-03-01T12:00:00.12+01:00', extra=xmp_props)))
        result = self.run_op({'version': V, 'operation': 'exportSidecar', 'media': self.items('a'),
                              'transfer': {'groups': ['descriptive', 'rights', 'rating', 'place', 'captureTime', 'location', 'camera', 'exposure', 'deviceSerials']}}, 's10')
        self.assertEqual(result['written'], 1)
        parsed = xmp.parse(self.read('s10', 'sidecars/a.xmp'))
        self.assertEqual(sorted(parsed), sorted(xmpwrite.PROPERTIES))
        self.assertEqual(len(parsed), 29)
        self.assertEqual((parsed['exif:GPSLongitude'][0]['value'], parsed['exifEX:GPSAltitudeRef'][0]['value'], parsed['exif:GPSTimeStamp'][0]['value']), ('139,45,36W', '3', '2026-03-01T11:00:00Z'))
        self.assertEqual((parsed['photoshop:DateCreated'][0]['value'], parsed['exif:DateTimeOriginal'][0]['value']), ('2026-03-01T12:00:00.12+01:00', '2026-03-01T12:00:00.12+01:00'))
        keys = self.json('s10', 'sidecar-report.json')['items'][0]['proofs']['S']['nativeKeys']
        self.assertEqual(len(keys), 29)
        self.assertEqual(sorted(keys), sorted(['XMP-dc:Title', 'XMP-dc:Description', 'XMP-dc:Rights', 'XMP-dc:Subject', 'XMP-dc:Creator', 'XMP-xmpRights:WebStatement', 'XMP-xmp:Rating', 'XMP-photoshop:City',
                                               'XMP-photoshop:Country', 'XMP-photoshop:DateCreated', 'XMP-tiff:Make', 'XMP-tiff:Model', 'XMP-exifEX:LensMake', 'XMP-exifEX:LensModel', 'XMP-exifEX:SerialNumber',
                                               'XMP-exifEX:LensSerialNumber', 'XMP-exif:ExposureTime', 'XMP-exif:FNumber', 'XMP-exif:FocalLength', 'XMP-exif:ExposureCompensation', 'XMP-exif:FocalLengthIn35mmFormat',
                                               'XMP-exifEX:PhotographicSensitivity', 'XMP-exif:DateTimeOriginal', 'XMP-exif:GPSLatitude', 'XMP-exif:GPSLongitude', 'XMP-exif:GPSAltitude', 'XMP-exif:GPSMapDatum',
                                               'XMP-exifEX:GPSAltitudeRef', 'XMP-exif:GPSDateTime']))
        self.assertEqual(self.verify('s10')['nativeReplay'], 'fresh-replay-matched')

    def test_a_refused_item_keeps_its_slot_and_the_others_continue(self):
        self.put('a.jpg', master())
        self.put('b.jpg', plain())
        self.put('c.jpg', master(seed=3))
        result = self.run_op({'version': V, 'operation': 'exportSidecar', 'media': self.items('a', 'b', 'c'), 'transfer': {'groups': ['descriptive']}}, 'partial')
        self.assertEqual((result['written'], result['refused'], result['setStatus']), (2, 1, 'partial'))
        slots = self.json('partial', 'verification.json')['artifacts']
        self.assertEqual([(s['kind'], s['identity']['kind'], s['identity']['item']) for s in slots[:3]], [('text', 'sidecar', 'a'), ('text', 'outcome', 'b'), ('text', 'sidecar', 'c')])
        self.assertEqual(self.json('partial', 'outcomes/b.json')['fault']['code'], 'SIDECAR_NOTHING_TO_WRITE')

    def test_E4H1_a_source_whose_offset_is_stated_only_by_a_carrier_without_its_own_time_is_refused_for_that_item_and_the_others_continue(self):
        self.put('a.jpg', f.fx.jpeg(dto=None, off='+09:00', sub=None, xmp=f.fx.xmp_properties(exif_dto='2024-03-01T10:20:30')))                     # Exif offset, no Exif time
        self.put('b.jpg', f.fx.jpeg(dto='2024:03:01 10:20:30', off=None, sub=None, iptc=[(2, 60, '102030+0900')]))                                     # IPTC time without its date
        self.put('c.jpg', f.fx.jpeg(dto='2024:03:01 10:20:30', off='+09:00', sub=None, seed=3))
        result = self.run_op({'version': V, 'operation': 'exportSidecar', 'media': self.items('a', 'b', 'c'), 'transfer': {'groups': ['captureTime']}}, 'h1e')
        self.assertEqual((result['written'], result['refused'], result['setStatus']), (1, 2, 'partial'))
        message = 'the source capture time cannot be used: its UTC offset is stated only by a carrier that does not state the local time itself, so no association with that time is invented'
        for item in ('a', 'b'):
            fault = self.json('h1e', 'outcomes/%s.json' % item)['fault']
            self.assertEqual((fault['code'], fault['message']), ('TRANSFER_TIME_COMPONENT_UNANCHORED', message), item)
        self.assertFalse((self.tmp / 'h1e' / 'sidecars' / 'a.xmp').exists())
        self.assertFalse((self.tmp / 'h1e' / 'sidecars' / 'b.xmp').exists())
        self.assertIn(b'2024-03-01T10:20:30+09:00', self.read('h1e', 'sidecars/c.xmp'))
        self.assertEqual(self.verify('h1e')['nativeReplay'], 'fresh-replay-matched')

    def test_S3_an_exif_text_with_a_control_character_refuses_only_that_item_as_not_xml(self):
        self.put('a.jpg', f.fx.jpeg(make='A', model='M', ifd0_extra=[f.a.ascii_entry(0x010E, 'a\x01b')]))
        self.put('b.jpg', master())
        result = self.run_op({'version': V, 'operation': 'exportSidecar', 'media': self.items('a', 'b'), 'transfer': {'groups': ['descriptive']}}, 'ctl')
        self.assertEqual((result['written'], result['refused']), (1, 1))
        fault = self.json('ctl', 'outcomes/a.json')['fault']
        self.assertEqual((fault['code'], fault['observed']['codePoint']), ('SIDECAR_TEXT_NOT_XML', 'U+0001'))

    def test_an_existing_adjacent_sidecar_is_never_merged_and_refuse_makes_it_a_refusal(self):
        self.put('a.jpg', master())
        self.put('a.xmp', b'<x:xmpmeta xmlns:x="adobe:ns:meta/"><rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"><rdf:Description rdf:about=""/></rdf:RDF></x:xmpmeta>')
        media = {'folder': {'path': str(self.media)}}
        result = self.run_op({'version': V, 'operation': 'exportSidecar', 'media': media, 'transfer': {'groups': ['descriptive']}}, 'ignore')
        self.assertEqual(result['written'], 1)
        fault = self.refuses({'version': V, 'operation': 'exportSidecar', 'media': media, 'transfer': {'groups': ['descriptive']}, 'policies': {'existingSidecar': 'refuse'}}, 'refuse', 'NO_USABLE_ITEMS')
        self.assertEqual(fault.observed['firstFaults'][0]['code'], 'SIDECAR_EXISTS')

    def test_all_items_refused_is_no_success(self):
        self.put('a.jpg', plain())
        self.refuses({'version': V, 'operation': 'exportSidecar', 'media': self.items('a'), 'transfer': {'groups': ['descriptive']}}, 'nothing', 'NO_USABLE_ITEMS')
        self.assertFalse((self.tmp / 'nothing' / 'sidecars').exists())

    def test_C6_the_malformed_xmp_of_a_source_is_unreadable_never_absent(self):
        self.put('a.jpg', f.fx.jpeg(make='A', model='M', xmp=f.fx.xmp_properties(extra='<dc:title><rdf:Alt>')))
        fault = self.refuses({'version': V, 'operation': 'exportSidecar', 'media': self.items('a'), 'transfer': {'groups': ['descriptive']}}, 'bad', 'NO_USABLE_ITEMS')
        first = fault.observed['firstFaults'][0]
        self.assertEqual((first['code'], first['observed']['faults'][0]['field'], first['observed']['faults'][0]['state']), ('TRANSFER_SOURCE_UNREADABLE', 'title', 'unreadable'))
        self.assertIn({'code': 'XMP_MALFORMED', 'family': 'xmp', 'location': 'dc:title', 'state': 'unreadable'}, [{k: v for k, v in s.items() if k != 'message'} for s in first['observed']['faults'][0]['sources']])

    def test_M_S8_a_doctype_injected_into_the_sidecar_is_not_reproducible(self):
        self.export()
        f.mutate_and_refresh(self, 'export', 'S8-doctype', lambda d: (d / 'sidecars/a.xmp').write_bytes((d / 'sidecars/a.xmp').read_bytes().replace(b'<x:xmpmeta', b'<!DOCTYPE x [<!ENTITY e "x">]><x:xmpmeta', 1)), 'SIDECAR_NOT_REPRODUCIBLE')

    def test_M_S9_a_tampered_native_listing_of_the_sidecar_is_an_anchor_mismatch(self):
        self.export()

        def change(d):
            text = (d / 'after.stdout').read_text()
            (d / 'after.stdout').write_text(text.replace('Harbour', 'Harbouu', 1))
        f.mutate_and_refresh(self, 'export', 'S9-listing', change, 'SIDECAR_ANCHOR_MISMATCH')

    def test_M_S1_a_changed_value_in_the_published_sidecar_is_not_reproducible(self):
        self.export()
        f.mutate_and_refresh(self, 'export', 'S1-value', lambda d: (d / 'sidecars/a.xmp').write_bytes((d / 'sidecars/a.xmp').read_bytes().replace(b'EOS 5D', b'EOS 5E')), 'SIDECAR_NOT_REPRODUCIBLE')

    def test_M_replay_without_a_trusted_runtime_fails_closed(self):
        self.export()
        from schemaxis.core.faults import SchemaxisError
        import json
        import os
        # A trusted runtime may also come from the configuration file (SCHEMAXIS_CONFIG), so absence needs a private empty one as well as no SCHEMAXIS_EXIFTOOL.
        configured = self.tmp / 'configured-runtime.json'
        configured.write_text(json.dumps({'version': 1, 'locations': {'exiftool': self.exe}}))
        empty = self.tmp / 'empty-runtime.json'
        empty.write_text(json.dumps({'version': 1, 'locations': {}}))
        saved = {name: os.environ.get(name) for name in ('SCHEMAXIS_EXIFTOOL', 'SCHEMAXIS_CONFIG')}
        try:
            os.environ.pop('SCHEMAXIS_EXIFTOOL', None)
            os.environ['SCHEMAXIS_CONFIG'] = str(configured)
            self.assertEqual(f.adaptor.verify(self.tmp / 'export')['nativeReplay'], 'fresh-replay-matched')
            os.environ['SCHEMAXIS_CONFIG'] = str(empty)
            with self.assertRaises(SchemaxisError) as raised:
                f.adaptor.verify(self.tmp / 'export')
            self.assertEqual(raised.exception.fault.code, 'NATIVE_REPLAY_UNAVAILABLE')
            self.assertEqual(raised.exception.fault.location, '$.runtime.exiftool')
        finally:
            for name, value in saved.items():
                if value is None:
                    os.environ.pop(name, None)
                else:
                    os.environ[name] = value


class NativeLocation(f.NativeCase):
    """The location group of exportSidecar (contract S-4..S-7, S-13) against real listings: every produced XMP key is anchored by the run itself."""

    def gps(self, alt, ref, version=b'0300', **more):
        gps = {'version': (2, 4, 0, 0), 'lat': [(35, 1), (7, 1), (24, 1)], 'lat_ref': 'N', 'lon': [(139, 1), (45, 1), (36, 1)], 'lon_ref': 'E', 'datum': 'WGS-84', **more}
        if alt is not None:
            gps.update(alt=alt, alt_ref=ref)
        self.put('a.jpg', f.fx.jpeg(make='A', model='M', exif_version=version, gps=gps))
        self.put('b.jpg', plain())

    def export(self, name, **policies):
        doc = {'version': V, 'operation': 'exportSidecar', 'media': self.items('a', 'b'), 'transfer': {'groups': ['location']}}
        if policies:
            doc['policies'] = policies
        return self.run_op(doc, name)

    def test_S4_a_negative_sea_level_height_is_written_with_exif3_reference_three(self):
        self.gps((25, 2), 3)
        self.export('s4')
        parsed = xmp.parse(self.read('s4', 'sidecars/a.xmp'))
        self.assertEqual((parsed['exif:GPSAltitude'][0]['value'], parsed['exifEX:GPSAltitudeRef'][0]['value']), ('25/2', '3'))
        self.assertEqual((parsed['exif:GPSLatitude'][0]['value'], parsed['exif:GPSLongitude'][0]['value'], parsed['exif:GPSMapDatum'][0]['value']), ('35,7,24N', '139,45,36E', 'WGS-84'))
        self.assertNotIn('exif:GPSAltitudeRef', parsed)                          # the obsolete property is never written
        row = self.json('s4', 'sidecar-report.json')['items'][0]
        self.assertEqual([i['code'] for i in row['infos']], ['exifToolCompositeLabelsSeaLevel'])
        self.record('test_exiftool_e4_sidecar.NativeLocation.S4', 'exportSidecar')

    def test_S4b_sea_level_code_two_carries_the_composite_misread_residual(self):
        self.gps((52317, 1000), 2)
        self.export('s4b')
        parsed = xmp.parse(self.read('s4b', 'sidecars/a.xmp'))
        self.assertEqual((parsed['exif:GPSAltitude'][0]['value'], parsed['exifEX:GPSAltitudeRef'][0]['value']), ('52317/1000', '2'))
        self.assertEqual([x['code'] for x in self.json('s4b', 'sidecar-report.json')['items'][0]['losses']], ['altitudeRefMisreadByExifTool13_55Composite'])

    def test_S5_an_ellipsoidal_height_in_an_exif3_file_is_reference_zero(self):
        self.gps((52317, 1000), 0)
        self.export('s5')
        parsed = xmp.parse(self.read('s5', 'sidecars/a.xmp'))
        self.assertEqual((parsed['exif:GPSAltitude'][0]['value'], parsed['exifEX:GPSAltitudeRef'][0]['value']), ('52317/1000', '0'))

    def test_S6_a_legacy_unspecified_reference_omits_the_altitude_or_refuses_by_policy(self):
        self.gps((25, 2), 0, version=b'0232', datum=None)
        self.export('s6')
        parsed = xmp.parse(self.read('s6', 'sidecars/a.xmp'))
        self.assertNotIn('exif:GPSAltitude', parsed)
        self.assertNotIn('exifEX:GPSAltitudeRef', parsed)
        self.assertEqual([x['code'] for x in self.json('s6', 'sidecar-report.json')['items'][0]['losses']], ['altitudeReferenceUnspecified'])
        fault = self.refuses({'version': V, 'operation': 'exportSidecar', 'media': self.items('a'), 'transfer': {'groups': ['location']}, 'policies': {'altitude': 'refuseUnlessReferenceKnown'}}, 's6r', 'NO_USABLE_ITEMS')
        self.assertEqual(fault.observed['firstFaults'][0]['code'], 'ALTITUDE_REFERENCE_UNSPECIFIED')

    def test_S7_stored_seconds_of_sixty_are_written_as_exact_decimal_minutes_and_the_info_is_carried(self):
        self.gps(None, None, lat=[(35, 1), (7, 1), (60, 1)])
        self.export('s7')
        parsed = xmp.parse(self.read('s7', 'sidecars/a.xmp'))
        self.assertEqual(parsed['exif:GPSLatitude'][0]['value'], '35,8.0N')
        row = self.json('s7', 'sidecar-report.json')['items'][0]
        self.assertIn('nonCanonicalSeconds60', [i['code'] for i in row['infos']])

    def test_S13_the_gps_time_stamp_is_a_utc_date_time_only_when_date_and_time_are_both_stored(self):
        self.gps(None, None, date='2024:03:01', time=[(1, 1), (20, 1), (30, 1)])
        self.export('s13')
        self.assertEqual(xmp.parse(self.read('s13', 'sidecars/a.xmp'))['exif:GPSTimeStamp'][0]['value'], '2024-03-01T01:20:30Z')


if __name__ == '__main__':
    unittest.main()
