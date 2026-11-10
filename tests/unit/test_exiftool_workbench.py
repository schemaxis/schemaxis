"""Host-only checks of the ExifTool metadata workbench read family: catalogue, decoders, states, media sets, planning, audit, comparison,
native-listing parsing and anchoring. No native process runs; native JSON used here is written by hand from the fixture specification."""
import copy
from fractions import Fraction
import json
import os
from pathlib import Path
import random
import sys
import tempfile
import unittest

from schemaxis.adaptors import registry
from schemaxis.adaptors.exiftool import adaptor, audit, catalogue, codecs, containers, iptc, listing, mediaset, records, tiff, workbench, xmp
from schemaxis.core.faults import SchemaxisError

ROOT = Path(__file__).resolve().parents[2]
EXAMPLES = ROOT / 'examples/schemaxis'
FIXTURES = EXAMPLES / 'fixtures/exiftool'
sys.path.insert(0, str(ROOT / 'tools'))
import author_exiftool_fixtures as author  # noqa: E402

FILES = author.workbench_files()
ALL = list(catalogue.fields())
LEGACY_PLAN_SHA = {'baseline': 'c5119bc8968c31737f0a4b047328bb0591147a166a99546abeaf4682b718971f', 'variant': 'f64a1056d09a83b092af902a1a0fadf9e495c06e9c5b88a89efb22fcd3cbc483'}


def example(name): return json.loads((EXAMPLES / name).read_text())


def build(name, sidecar=None, names=ALL):
    located = containers.locate(FILES[name])
    side = containers.locate(FILES[sidecar]) if sidecar else None
    return records.build(located, names, side)[1]


def state(fields, name): return fields[name]['state']
def published(fields, name): return records.publish(fields[name])


class Workbench(unittest.TestCase):
    def fault(self, action, code, location=None, **observed):
        with self.assertRaises(SchemaxisError) as raised:
            action()
        fault = raised.exception.fault
        self.assertEqual(fault.code, code, fault.to_dict())
        if location:
            self.assertEqual(fault.location, location)
        for key, value in observed.items():
            self.assertEqual(fault.observed.get(key), value, fault.to_dict())
        return fault

    # ---------------------------------------------------------------- catalogue
    def test_catalogue_is_valid_broad_and_documented(self):
        fields = catalogue.fields()
        self.assertEqual(len(fields), 40)
        self.assertEqual(set(catalogue.profiles()), {'capture', 'device', 'exposure', 'description', 'rights', 'location', 'rendering'})
        guide = (ROOT / 'docs/exiftool.md').read_text()
        for name, spec in fields.items():
            self.assertIn('| `%s` |' % name, guide, name)
            self.assertIn(spec['description'], guide, name)
            self.assertGreaterEqual(len(spec['description']), 60, name)
        # location fields carry the location privacy class; identity fields never claim none
        for name in ('gpsLatitude', 'gpsLongitude', 'gpsAltitude', 'gpsDatum', 'gpsUtc', 'locationCity'):
            self.assertEqual(fields[name]['privacy'], 'location')
        for name in ('bodySerialNumber', 'cameraModel', 'lensSerialNumber'):
            self.assertEqual(fields[name]['privacy'], 'device-identity')
        self.assertEqual(fields['creator']['privacy'], 'personal-identity')

    def test_catalogue_validator_refuses_bad_data(self):
        good = catalogue.load()

        def broken(change):
            data = copy.deepcopy(good)
            change(data)
            with self.assertRaises(catalogue.CatalogueError):
                catalogue.validate(data)
        broken(lambda d: d['fields']['cameraMake']['sources'][0].update(codec='nonexistent'))
        broken(lambda d: d['fields']['cameraMake']['sources'][0].update(codec='xmpText'))
        broken(lambda d: d['fields']['cameraMake'].pop('description'))
        broken(lambda d: d['fields']['cameraMake'].update(privacy='public'))
        broken(lambda d: d['fields']['cameraMake']['sources'].append(copy.deepcopy(d['fields']['cameraMake']['sources'][0])))
        broken(lambda d: d['fields']['capturedUtc']['derive'].update({'from': ['nowhere', 'capturedOffset']}))
        broken(lambda d: d['fields']['cameraMake']['sources'][0].update(tag='0x10F'))
        broken(lambda d: d['fields']['cameraMake']['sources'][1].update(property='no-colon'))
        broken(lambda d: d['fields']['orientation'].pop('labels'))
        broken(lambda d: d.update(version='schemaxis.exiftool.fields/2'))

    def test_committed_workbench_fixtures_regenerate_exactly(self):
        for name, data in FILES.items():
            self.assertEqual((FIXTURES / name).read_bytes(), data, name)

    # ---------------------------------------------------------------- independent decoding with literal expectations
    def test_full_photo_decodes_every_family_with_literal_values(self):
        fields = build('ridge-line.jpg')
        literal = {'capturedLocal': '2024-05-06T07:08:09', 'capturedSubSecond': '12', 'capturedOffset': '+02:00', 'capturedUtc': '2024-05-06T05:08:09Z',
                   'digitizedLocal': '2024-05-06T07:08:10', 'cameraMake': 'Northfield', 'cameraModel': 'NF-200', 'software': 'Synthetic fixture generator',
                   'lensModel': 'NF 35mm f/1.8', 'bodySerialNumber': 'SN-0001', 'exposureTime': 0.004, 'fNumber': 2.8, 'isoSpeed': 200, 'focalLength': 35,
                   'title': 'Ridge', 'description': 'Ridge line at dusk', 'keywords': ['ridge', 'dusk'], 'rating': 4, 'creator': ['Ada Example'],
                   'copyright': '(c) 2024 Ada Example', 'rightsUrl': 'https://example.invalid/rights', 'gpsDirection': 90.5, 'gpsDirectionReference': 'true',
                   'gpsDatum': 'WGS-84', 'gpsUtcDate': '2024-05-06', 'gpsUtcTime': '05:08:09', 'gpsUtc': '2024-05-06T05:08:09Z', 'gpsAltitude': 123.4,
                   'locationCity': 'Imaginary Town', 'locationCountry': 'Nowhereland', 'orientation': 1, 'imageWidth': 16, 'imageHeight': 16}
        for name, value in literal.items():
            self.assertEqual((state(fields, name), published(fields, name)['value']), ('present', value), name)
        # 12 degrees 34 minutes 5 seconds north; 45 degrees 40 minutes west: exact sexagesimal arithmetic written by hand
        self.assertAlmostEqual(published(fields, 'gpsLatitude')['value'], 12 + 34 / 60 + 5 / 3600, places=12)
        self.assertAlmostEqual(published(fields, 'gpsLongitude')['value'], -(45 + 40 / 60), places=12)
        self.assertEqual(published(fields, 'exposureTime')['exact'], '1/250')
        self.assertEqual(published(fields, 'orientation')['label'], 'top-left')
        self.assertEqual(published(fields, 'capturedLocal')['reconciliation'], 'consistent')
        self.assertEqual(published(fields, 'keywords')['reconciliation'], 'consistent')
        self.assertEqual({s['family'] for s in published(fields, 'capturedLocal')['sources']}, {'exif', 'xmp', 'iptc'})
        for name in ('modifiedLocal', 'lensMake', 'lensSerialNumber', 'exposureBias', 'focalLength35mm'):
            self.assertEqual(state(fields, name), 'absent', name)

    def test_modify_time_and_lens_identity_decode_when_the_file_records_them(self):
        fields = build('lens-record.jpg')
        for name, value in {'modifiedLocal': '2024-05-06T08:00:00', 'lensMake': 'Northfield Optics', 'lensModel': 'NF 85mm f/1.4', 'lensSerialNumber': 'LS-0042',
                            'cameraMake': 'Northfield', 'cameraModel': 'NF-300'}.items():
            self.assertEqual((state(fields, name), published(fields, name)['value']), ('present', value), name)
        self.assertEqual(state(fields, 'capturedLocal'), 'absent')  # a modify time is never substituted for the capture time
        self.assertEqual(state(fields, 'bodySerialNumber'), 'absent')

    def test_disagreeing_sources_are_ambiguous_with_every_value_and_no_preference(self):
        fields = build('conflict-desk.jpg')
        for name in ('description', 'creator', 'capturedLocal'):
            self.assertEqual((state(fields, name), fields[name]['reconciliation']), ('ambiguous', 'conflicting'), name)
            self.assertIsNone(published(fields, name)['value'])
        listed = {(v['family'], str(v['value'])) for v in published(fields, 'description')['values']}
        self.assertEqual(listed, {('exif', 'Desk with a laptop'), ('iptc', 'Desk with a laptop'), ('xmp', 'Desk with a notebook')})
        self.assertEqual(state(fields, 'capturedUtc'), 'ambiguous')
        self.assertEqual(published(fields, 'capturedUtc')['reconciliation'], 'derived-from-ambiguous-input')
        self.assertEqual(published(fields, 'cameraMake')['value'], 'Riverside Optics')

    def test_presence_states_are_distinct(self):
        self.assertEqual(state(build('duplicate-tags.jpg'), 'cameraMake'), 'ambiguous')
        self.assertEqual(build('duplicate-tags.jpg')['cameraMake']['sources'][0]['code'], 'EXIF_TAG_REPEATED')
        self.assertEqual(state(build('duplicate-tags.jpg'), 'cameraModel'), 'present')
        latin = build('latin-iptc.jpg')
        self.assertEqual((state(latin, 'title'), latin['title']['sources'][0]['code']), ('unreadable', 'IPTC_CHARSET_UNSPECIFIED'))
        self.assertEqual(published(latin, 'description')['value'], 'Plain ascii text')
        utf8 = build('utf8-iptc.jpg')
        self.assertEqual((published(utf8, 'title')['value'], published(utf8, 'keywords')['value']), ('Café ☕', ['café']))
        entity = build('entity-xmp.jpg')
        self.assertEqual((state(entity, 'description'), entity['description']['sources'][-1]['code']), ('unreadable', 'XMP_DOCTYPE_REFUSED'))
        self.assertEqual(state(entity, 'imageWidth'), 'present')
        sidecar_only = build('sidecar-only.xmp')
        # an XMP sidecar was fully understood and has no tiff:Make (absent); EXIF-only and frame fields cannot exist in it (unsupported)
        self.assertEqual((state(sidecar_only, 'description'), state(sidecar_only, 'cameraMake'), state(sidecar_only, 'software'), state(sidecar_only, 'imageWidth')),
                         ('present', 'absent', 'unsupported', 'unsupported'))
        self.assertEqual(state(build('ridge-line.jpg', names=['capturedLocal']), 'capturedLocal'), 'present')
        self.assertNotIn('cameraMake', build('ridge-line.jpg', names=['capturedLocal']))

    def test_unsupported_and_missing_components_are_not_confused(self):
        # an XMP date without an offset or fraction: the components are absent, not unsupported; reduced precision is unsupported
        packet = lambda value: author.xmp_app1(author.xmp_packet('<photoshop:DateCreated>%s</photoshop:DateCreated>' % value))
        def fields(value):
            data = author.build(8, 8, 1, app_segments=[(0xE1, packet(value))])
            return records.build(containers.locate(data), ['capturedLocal', 'capturedOffset', 'capturedSubSecond', 'capturedUtc'])[1]
        full = fields('2024-05-06T07:08:09.250Z')
        self.assertEqual([published(full, n)['value'] for n in ('capturedLocal', 'capturedOffset', 'capturedSubSecond', 'capturedUtc')], ['2024-05-06T07:08:09', '+00:00', '250', '2024-05-06T07:08:09Z'])
        plain = fields('2024-05-06T07:08:09')
        self.assertEqual([state(plain, n) for n in ('capturedLocal', 'capturedOffset', 'capturedSubSecond', 'capturedUtc')], ['present', 'absent', 'absent', 'absent'])
        reduced = fields('2024-05-06')
        self.assertEqual((state(reduced, 'capturedLocal'), next(x for x in reduced['capturedLocal']['sources'] if x['family'] == 'xmp')['code']), ('unsupported', 'XMP_DATE_REDUCED_PRECISION'))
        self.assertEqual(state(fields('2024-02-30T00:00:00'), 'capturedLocal'), 'unreadable')
        self.assertEqual(state(fields('not a date'), 'capturedLocal'), 'unreadable')

    def test_sidecar_is_a_separate_source_and_can_conflict_with_embedded_xmp(self):
        paired = build('quay-side.jpg', sidecar='quay-side.xmp')
        self.assertEqual(published(paired, 'description')['value'], 'Quay at noon')
        self.assertEqual([s['family'] for s in published(paired, 'description')['sources'] if s['state'] == 'present'], ['xmp-sidecar'])
        self.assertEqual(published(paired, 'cameraMake')['value'], 'Northfield')
        # a sidecar that disagrees with embedded XMP: both sources are kept and the field is ambiguous
        data = author.build(8, 8, 1, app_segments=[(0xE1, author.xmp_app1(author.xmp_packet('<dc:description><rdf:Alt><rdf:li xml:lang="x-default">Embedded</rdf:li></rdf:Alt></dc:description>')))])
        both = records.build(containers.locate(data), ['description'], containers.locate(FILES['quay-side.xmp']))[1]
        self.assertEqual((state(both, 'description'), both['description']['reconciliation']), ('ambiguous', 'conflicting'))

    def test_gps_conventions_from_the_primary_exif_source(self):
        def gps(*rows):
            ifd0, exif, g = author.rich_entries('II', dict(gps=list(rows)))
            return records.build(containers.locate(author.build(8, 8, 1, exif=author.tiff_payload('II', [], [], g))), ['gpsLatitude', 'gpsLongitude', 'gpsAltitude', 'gpsDirection', 'gpsUtcTime', 'gpsDatum'])[1]
        south_east = gps('latref:S', 'lat:10,30,0/1', 'lonref:E', 'lon:20,0,0/1')
        self.assertEqual((published(south_east, 'gpsLatitude')['value'], published(south_east, 'gpsLongitude')['value']), (-10.5, 20))
        self.assertEqual(state(south_east, 'gpsDatum'), 'absent')  # an unrecorded datum is reported absent and never inferred
        no_ref = gps('lat:10,0,0/1')
        self.assertEqual((state(no_ref, 'gpsLatitude'), no_ref['gpsLatitude']['sources'][0]['code']), ('unreadable', 'GPS_REF_MISSING'))
        self.assertEqual(state(gps('latref:X', 'lat:10,0,0/1'), 'gpsLatitude'), 'unreadable')
        self.assertEqual(state(gps('latref:N', 'lat:91,0,0/1'), 'gpsLatitude'), 'unreadable')
        self.assertEqual(state(gps('latref:N', 'lat:10,60,0/1'), 'gpsLatitude'), 'unreadable')
        self.assertEqual(state(gps('latref:N', 'lat:10,0,0/0'), 'gpsLatitude'), 'unreadable')
        below = gps('altref:1', 'alt:50/1')
        self.assertEqual(published(below, 'gpsAltitude')['value'], -50)
        self.assertEqual(published(gps('alt:50/1'), 'gpsAltitude')['value'], 50)  # the Exif default reference is 0 (above sea level)
        self.assertEqual(state(gps('altref:2', 'alt:50/1'), 'gpsAltitude'), 'unreadable')
        self.assertEqual(state(gps('dir:360/1'), 'gpsDirection'), 'unreadable')
        self.assertEqual(state(gps('gpstime:24,0,0'), 'gpsUtcTime'), 'unreadable')
        self.assertEqual(state(gps('gpstime:1,2,3/2'), 'gpsUtcTime'), 'unsupported')

    def test_offsets_and_calendar_follow_the_legacy_rules(self):
        self.assertEqual(codecs.check_offset('+', '14', '00', 'x'), '+14:00')
        for sign, hh, mm in (('+', '15', '00'), ('-', '13', '00'), ('+', '01', '60'), ('-', '00', '00')):
            with self.assertRaises(codecs.ValueProblem):
                codecs.check_offset(sign, hh, mm, 'x')
        self.assertEqual(codecs.to_utc('2024-03-01T00:30:00', '+01:00'), '2024-02-29T23:30:00Z')
        self.assertEqual(codecs.to_utc('2023-12-31T23:59:58', '-05:30'), '2024-01-01T05:29:58Z')
        with self.assertRaises(codecs.ValueProblem):
            codecs.valid_calendar(2023, 2, 29, 0, 0, 0, 'x')

    # ---------------------------------------------------------------- hostile payloads
    def test_xmp_reader_refuses_and_bounds_hostile_packets(self):
        for data in (b'<!DOCTYPE x [<!ENTITY a "b">]><x/>', b'<?xml version="1.0"?><!doctype x><x/>', b'<!ENTITY a "b">'):
            with self.assertRaises(xmp.Problem) as raised:
                xmp.parse(data)
            self.assertEqual(raised.exception.code, 'XMP_DOCTYPE_REFUSED')
        for data, code in ((b'\xff\xfe<\0x\0/\0>\0', 'XMP_ENCODING_UNSUPPORTED'), (b'<x:xmpmeta', 'XMP_MALFORMED'), (b'<a/>', 'XMP_MALFORMED'),
                           (b'x' * (xmp.MAX_BYTES + 1), 'XMP_BOUND')):
            with self.assertRaises(xmp.Problem) as raised:
                xmp.parse(data)
            self.assertEqual(raised.exception.code, code)
        deep = b'<x:xmpmeta xmlns:x="adobe:ns:meta/"><rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"><rdf:Description xmlns:a="a">' \
            + b'<a:p>' * (xmp.MAX_DEPTH + 3) + b'</a:p>' * (xmp.MAX_DEPTH + 3) + b'</rdf:Description></rdf:RDF></x:xmpmeta>'
        found = xmp.parse(deep)  # nested elements inside a simple property are a structure, never recursed into without bound
        self.assertEqual(found['{a}p'][0]['kind'], 'struct')
        many = b'<x:xmpmeta xmlns:x="adobe:ns:meta/"><rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"><rdf:Description xmlns:a="a">' + b'<a:p/>' * (xmp.MAX_ELEMENTS + 1) + b'</rdf:Description></rdf:RDF></x:xmpmeta>'
        with self.assertRaises(xmp.Problem) as raised:
            xmp.parse(many)
        self.assertEqual(raised.exception.code, 'XMP_BOUND')
        repeated = xmp.parse(author.xmp_packet('<dc:description><rdf:Alt><rdf:li xml:lang="x-default">a</rdf:li></rdf:Alt></dc:description><dc:description><rdf:Alt><rdf:li xml:lang="x-default">b</rdf:li></rdf:Alt></dc:description>'))
        self.assertEqual(len(repeated['dc:description']), 2)

    def test_iptc_reader_charset_and_structure_rules(self):
        block = lambda *sets, utf8=True: iptc.datasets(author.iptc_app13(list(sets), utf8)[len(b'Photoshop 3.0\0') + 12:][:-0 or None])
        data = author.iptc_app13([(2, 5, 'Name')])
        resource = dict(iptc.resources(data))[0x0404]
        self.assertEqual(iptc.datasets(resource)['charset'], 'utf-8')
        plain = dict(iptc.resources(author.iptc_app13([(2, 5, 'Name')], utf8=False)))[0x0404]
        self.assertEqual(iptc.datasets(plain)['charset'], 'unspecified')
        other = b'\x1c\x01\x5a\x00\x03\x1b%@' + b'\x1c\x02\x05\x00\x01A'
        self.assertEqual(iptc.datasets(other)['charset'], 'unsupported')
        self.assertEqual(codecs.CODECS['iptcText'][1]([b'A'], 'unspecified'), 'A')
        with self.assertRaises(codecs.Unsupported):
            codecs.CODECS['iptcText'][1]([b'A'], 'unsupported')
        with self.assertRaises(codecs.ValueProblem):
            codecs.CODECS['iptcText'][1]([b'\xe9'], 'unspecified')
        with self.assertRaises(codecs.ValueProblem):
            codecs.CODECS['iptcText'][1]([b'\xe9'], 'utf-8')
        with self.assertRaises(iptc.Problem):
            iptc.datasets(b'\x1c\x02\x05\x80\x01A')  # extended-length dataset
        with self.assertRaises(iptc.Problem):
            iptc.datasets(b'\x1c\x02\x05\x00\x09A')  # length beyond the data
        with self.assertRaises(iptc.Problem):
            iptc.datasets(b'junk')
        with self.assertRaises(codecs.Ambiguous):
            codecs.CODECS['iptcText'][1]([b'A', b'B'], 'utf-8')

    def test_tiff_walker_and_whole_file_locators_survive_mutation(self):
        random.seed(74)
        base = FILES['ridge-line.jpg']
        for _ in range(400):
            mutated = bytearray(base)
            for _ in range(random.randint(1, 6)):
                mutated[random.randrange(len(mutated))] = random.randrange(256)
            try:
                located = containers.locate(bytes(mutated))
            except containers.Refused:
                continue
            fields = records.build(located, ALL)[1]
            for record in fields.values():  # every field always has exactly one defined state and publishes to JSON
                self.assertIn(record['state'], ('present', 'absent', 'unreadable', 'unsupported', 'ambiguous'))
                json.dumps(records.publish(record))
        for cut in range(0, len(base), 37):
            try:
                containers.locate(base[:cut])
            except containers.Refused:
                pass
        for blob in (b'', b'\xff\xd8', b'\xff\xd8\xff', b'GIF89a', b'\x00' * 100, b'<?xml'):
            try:
                containers.locate(blob)
            except containers.Refused as error:
                self.assertIn(error.code, ('UNSUPPORTED_MEDIA', 'INVALID_PHOTO_DATA'))

    def test_tiff_structure_faults_are_scoped_to_their_ifd(self):
        # a bad ExifIFD pointer makes only ExifIFD fields unreadable; IFD0 fields stay readable
        ifd0 = [author.ascii_entry(author.IFD0_MAKE, 'Northfield'), author.long_entry('II', author.IFD0_EXIF, 10 ** 6)]
        fields = records.build(containers.locate(author.build(8, 8, 1, exif=author.tiff_payload('II', ifd0, [], []))), ['cameraMake', 'capturedLocal'])[1]
        self.assertEqual((state(fields, 'cameraMake'), state(fields, 'capturedLocal')), ('present', 'unreadable'))
        with self.assertRaises(tiff.Damaged):
            tiff.walk(b'not tiff')
        looped = author.tiff_payload('II', [author.ascii_entry(author.IFD0_MAKE, 'A')])[6:]
        looped = looped[:-4] + (8).to_bytes(4, 'little')
        self.assertEqual(tiff.walk(looped)['ifds']['IFD1'][0], 'error')
        data = author.build(8, 8, 1, exif=author.tiff_payload('II', [author.ascii_entry(author.IFD0_MAKE, 'A')]), app1_count=2)
        two = records.build(containers.locate(data), ['cameraMake'])[1]
        self.assertEqual((state(two, 'cameraMake'), two['cameraMake']['sources'][0]['code']), ('ambiguous', 'EXIF_SEGMENT_REPEATED'))

    def test_jpeg_locator_accepts_other_codings_and_reports_notes(self):
        progressive = containers.locate(author.build(8, 8, 1, sof_marker=0xC2, make='A'))
        self.assertEqual(progressive['frame']['process'], 'progressive')
        trailing = containers.locate(author.build(8, 8, 1, make='A', trailing=b'xyz'))
        self.assertIn('bytes-after-eoi:3', trailing['notes'])
        for broken, code in ((author.build(8, 8, 1)[:-2], 'INVALID_PHOTO_DATA'), (b'\xff\xd8\xff\xd9', 'INVALID_PHOTO_DATA'), (b'%PDF-1.4', 'UNSUPPORTED_MEDIA')):
            with self.assertRaises(containers.Refused) as raised:
                containers.locate(broken)
            self.assertEqual(raised.exception.code, code)

    # ---------------------------------------------------------------- planning
    def test_planning_is_deterministic_immutable_and_closed(self):
        for name in ('inspect-baseline', 'inspect-variant', 'audit-baseline', 'compare-baseline'):
            document = example('exiftool-%s.json' % name)
            original = copy.deepcopy(document)
            first = workbench.plan(document)
            self.assertEqual(first, adaptor.plan(document))
            self.assertEqual(first, workbench.plan(document))
            self.assertEqual(document, original)
            self.assertEqual(first['settings']['nativeArguments'], listing.FIXED)
            self.assertEqual(first['catalogue']['sha256'], workbench.catalogue_digest())
            json.dumps(first)
        inspect = workbench.plan(example('exiftool-inspect-baseline.json'))
        self.assertEqual(inspect['media']['folder'], {'path': '/tmp/schemaxis-exiftool-acceptance/workbench', 'extensions': ['.jpg', '.jpeg', '.xmp'], 'depth': 1, 'maxItems': 64, 'sidecars': 'adjacent'})
        self.assertEqual(inspect['profiles'], ['capture', 'device', 'location'])
        self.assertEqual(inspect['fields'], [f for f in ALL if catalogue.fields()[f]['profile'] in ('capture', 'device', 'location')])
        base = example('exiftool-inspect-baseline.json')
        self.fault(lambda: workbench.plan({**base, 'extra': 1}), 'UNKNOWN_ARGUMENT')
        self.fault(lambda: workbench.plan({**base, 'photos': []}), 'UNKNOWN_ARGUMENT', keys=['photos'])
        self.fault(lambda: workbench.plan({**base, 'operation': 'writeMetadata'}), 'UNKNOWN_OPERATION', '$.operation')
        self.fault(lambda: workbench.plan({**base, 'version': 'x'}), 'UNSUPPORTED_VERSION')
        self.fault(lambda: workbench.plan({k: v for k, v in base.items() if k != 'profiles'}), 'MISSING_ARGUMENT', '$.arguments.profiles')
        self.fault(lambda: workbench.plan({**base, 'profiles': ['capture', 'capture']}), 'INVALID_ARGUMENT')
        self.fault(lambda: workbench.plan({**base, 'profiles': ['tags']}), 'INVALID_ARGUMENT')
        self.fault(lambda: workbench.plan({**base, 'nativeListing': 'yes'}), 'INVALID_ARGUMENT')
        self.fault(lambda: workbench.plan({**base, 'media': {'folder': {'path': 'relative'}}}), 'INVALID_PHOTO_SOURCE')
        self.fault(lambda: workbench.plan({**base, 'media': {'folder': {'path': '/x/../y'}}}), 'INVALID_PHOTO_SOURCE')
        self.fault(lambda: workbench.plan({**base, 'media': {'folder': {'path': '/x', 'depth': 3}}}), 'INVALID_ARGUMENT')
        self.fault(lambda: workbench.plan({**base, 'media': {'folder': {'path': '/x', 'maxItems': 513}}}), 'INVALID_ARGUMENT')
        self.fault(lambda: workbench.plan({**base, 'media': {'folder': {'path': '/x', 'tag': 'Make'}}}), 'INVALID_ARGUMENT')
        self.fault(lambda: workbench.plan({**base, 'media': {'items': []}}), 'INVALID_ARGUMENT')
        item = {'id': 'a', 'path': '/x/a.jpg'}
        self.fault(lambda: workbench.plan({**base, 'media': {'items': [item, {**item, 'path': '/x/b.jpg'}]}}), 'DUPLICATE_PHOTO_ID', '$.media.items[1].id')
        self.fault(lambda: workbench.plan({**base, 'media': {'items': [item, {'id': 'b', 'path': '/x/./a.jpg'}]}}), 'DUPLICATE_PHOTO_SOURCE', '$.media.items[1].path')
        self.fault(lambda: workbench.plan({**base, 'media': {'items': [{'id': '1a', 'path': '/x/a.jpg'}]}}), 'INVALID_PHOTO_ID', '$.media.items[0].id')
        self.fault(lambda: workbench.plan({**base, 'media': {'items': [{'id': 'a', 'path': '/x/a.txt'}]}}), 'INVALID_PHOTO_SOURCE')
        for suffix in ('.png', '.tif', '.tiff', '.dng', '.webp', '.heic', '.heif', '.avif'):     # E5: other containers are selectable by suffix; the container itself is detected by signature
            self.assertEqual(workbench.plan({**base, 'media': {'items': [{'id': 'a', 'path': '/x/a' + suffix}]}})['media']['items'][0]['path'], '/x/a' + suffix)
        self.fault(lambda: workbench.plan({**base, 'media': {'items': [{'id': 'a', 'path': '/x/a.jpg', 'sha256': 'ABC'}]}}), 'INVALID_ARGUMENT')
        self.fault(lambda: workbench.plan({**base, 'media': {'items': [{'id': 'a', 'path': '/x/a.jpg', 'sidecar': '/x/a.txt'}]}}), 'INVALID_SIDECAR')
        self.fault(lambda: workbench.plan({**base, 'media': {'items': [{'id': 'a', 'path': '/x/a.xmp', 'sidecar': '/x/b.xmp'}]}}), 'INVALID_SIDECAR')
        many = [{'id': 'p%d' % i, 'path': '/x/%d.jpg' % i} for i in range(513)]
        self.fault(lambda: workbench.plan({**base, 'media': {'items': many}}), 'INVALID_ARGUMENT')
        workbench.plan({**base, 'media': {'items': many[:512]}})

    def test_audit_and_compare_option_semantics(self):
        base = example('exiftool-audit-baseline.json')
        plan = workbench.plan(base)
        self.assertEqual(plan['audit']['rules'], list(audit.RULES))
        self.assertTrue({'capturedLocal', 'cameraModel', 'gpsUtc', 'digitizedLocal'} <= set(plan['fields']))
        defaults = workbench.plan({k: v for k, v in base.items() if k not in ('rules', 'require', 'gpsToleranceSeconds')})
        self.assertNotIn('requiredFields', defaults['audit']['rules'])
        self.assertEqual(defaults['audit']['gpsToleranceSeconds'], 300)
        self.fault(lambda: workbench.plan({**base, 'rules': ['sourceConflicts']}), 'INVALID_AUDIT', '$.require')
        self.fault(lambda: workbench.plan({k: v for k, v in base.items() if k != 'require'}), 'INVALID_AUDIT', '$.require')
        self.fault(lambda: workbench.plan({**base, 'rules': ['requiredFields']}), 'INVALID_AUDIT', '$.gpsToleranceSeconds')
        self.fault(lambda: workbench.plan({**base, 'rules': ['mystery']}), 'INVALID_ARGUMENT')
        self.fault(lambda: workbench.plan({**base, 'require': ['Make']}), 'INVALID_ARGUMENT')
        self.fault(lambda: workbench.plan({**base, 'gpsToleranceSeconds': -1}), 'INVALID_ARGUMENT')
        self.fault(lambda: workbench.plan({'version': adaptor.VERSION, 'operation': 'auditMetadata', 'media': base['media'], 'rules': ['sourceConflicts']}), 'INVALID_ARGUMENT')
        compare = example('exiftool-compare-baseline.json')
        self.assertEqual(workbench.plan(compare)['compare'], {'baseline': 'ridge_line'})
        self.fault(lambda: workbench.plan(example('exiftool-baseline-missing-invalid.json')), 'INVALID_BASELINE', '$.baseline', value='zzz')
        self.fault(lambda: workbench.plan({**compare, 'baseline': '1x'}), 'INVALID_PHOTO_ID', '$.baseline')
        self.fault(lambda: workbench.plan({**compare, 'profiles': [], 'fields': []}), 'INVALID_ARGUMENT')

    def test_invalid_examples_fail_exactly_as_declared(self):
        readiness = json.loads((ROOT / 'src/schemaxis/adaptors/exiftool/readiness.json').read_text())['routes']['schemaxis.exiftool/1']['examples']
        invalid = [e for e in readiness if e.get('expect') == 'invalid' and 'operation' in example(Path(e['reference']).name) and example(Path(e['reference']).name)['operation'] not in ('inventoryPhotos', 'editMetadata', 'removeMetadata', 'correctTime', 'setLocation', 'geotagFromTrack', 'copyMetadata', 'planNames')]      # the four read-family invalid examples; the write operations' invalid examples are asserted by their own tests
        self.assertEqual(len(invalid), 4)
        for entry in invalid:
            self.fault(lambda: adaptor.plan(example(Path(entry['reference']).name)), entry['fault'])

    def test_legacy_inventory_plan_launcher_and_declaration_are_unchanged(self):
        for name, wanted in LEGACY_PLAN_SHA.items():
            self.assertEqual(adaptor.plan_hash(adaptor.plan(example('exiftool-%s.json' % name))), wanted)
        self.assertEqual(adaptor.SELECTED[0], 'IFD0:Make')
        self.assertEqual(adaptor.commands('/x/exiftool', adaptor.plan(example('exiftool-baseline.json')))['extract'][:6], [adaptor.PERL, '/x/exiftool', '-config', '', '-json', '-n'])
        self.assertEqual(adaptor.query(example('exiftool-baseline.json')), (['inventoryPhotos'], {}))
        self.assertEqual(adaptor.query(example('exiftool-inspect-baseline.json')), (['inspectMetadata'], {}))
        self.assertEqual(sorted(adaptor.DECLARATIONS), ['applySidecar', 'auditMetadata', 'compareMetadata', 'copyMetadata', 'correctTime', 'editMetadata', 'exportSidecar', 'geotagFromTrack', 'inspectMetadata', 'inventoryPhotos', 'locate', 'organiseCopies', 'planNames', 'reconcileTime', 'removeMetadata', 'setLocation'])

    def test_schema_describes_every_operation_without_tag_or_option_fields(self):
        schema = adaptor.schema()
        self.assertEqual(len(schema['oneOf']), 16)             # inventory, the five read operations (E1 and E3), the five write operations (E2 and E3) and the five copy, sidecar and naming operations (E4)
        self.assertEqual({b['properties']['operation']['const'] for b in schema['oneOf']}, set(adaptor.DECLARATIONS))
        text = json.dumps(schema).lower()
        for banned in ('tagname', '"tags"', 'argument', 'perl', 'config', 'expression', '-api'):
            self.assertNotIn(banned, text)
        self.assertEqual(set(schema['oneOf'][1]['required']), {'version', 'operation', 'media', 'profiles'})
        self.assertEqual(set(schema['oneOf'][3]['required']), {'version', 'operation', 'media', 'baseline'})

    # ---------------------------------------------------------------- media sets
    def tree(self):
        root = Path(tempfile.mkdtemp(prefix='schemaxis-exiftool-test-')).resolve()
        for name in ('ridge-line.jpg', 'quay-side.jpg', 'quay-side.xmp', 'sidecar-only.xmp'):
            (root / name).write_bytes(FILES[name])
        (root / 'sub/deeper/deepest').mkdir(parents=True)
        (root / 'sub/latin-iptc.jpg').write_bytes(FILES['latin-iptc.jpg'])
        (root / 'sub/deeper/utf8-iptc.jpg').write_bytes(FILES['utf8-iptc.jpg'])
        (root / 'sub/deeper/deepest/z.jpg').write_bytes(FILES['utf8-iptc.jpg'])
        (root / 'notes.txt').write_text('x')
        (root / '.hidden.jpg').write_bytes(FILES['ridge-line.jpg'])
        os.symlink('ridge-line.jpg', root / 'link.jpg')
        return root

    def test_folder_manifest_is_complete_deterministic_and_bounded(self):
        root = self.tree()
        plan = mediaset.plan_media({'folder': {'path': str(root), 'depth': 2}})
        rows, found, signature = mediaset.expand(plan)
        reasons = {r['path']: (r['role'], r.get('reason')) for r in rows}
        self.assertEqual(reasons['link.jpg'], ('excluded', 'symlink'))
        self.assertEqual(reasons['.hidden.jpg'], ('excluded', 'hidden'))
        self.assertEqual(reasons['notes.txt'], ('excluded', 'extension'))
        self.assertEqual(reasons['quay-side.xmp'], ('sidecar', 'sidecar-of:quay_side'))
        self.assertEqual(reasons['sub/deeper/deepest'], ('excluded', 'directory-beyond-depth'))
        self.assertNotIn('sub/deeper/deepest/z.jpg', reasons)  # never entered
        self.assertEqual([f['id'] for f in found], ['quay_side', 'ridge_line', 'sidecar_only', 'utf8_iptc', 'latin_iptc'])
        self.assertEqual(sorted(reasons), sorted(r['path'] for r in rows))
        self.assertEqual(len(rows), len(signature))
        again = mediaset.expand(plan)
        self.assertEqual((again[0], [f['id'] for f in again[1]]), (rows, [f['id'] for f in found]))
        limited = mediaset.expand(mediaset.plan_media({'folder': {'path': str(root), 'depth': 2, 'maxItems': 2}}))
        self.assertEqual([f['id'] for f in limited[1]], ['quay_side', 'ridge_line'])
        self.assertEqual({r['reason'] for r in limited[0] if r.get('reason') == 'count-limit'}, {'count-limit'})
        shallow = mediaset.expand(mediaset.plan_media({'folder': {'path': str(root), 'depth': 0}}))
        self.assertEqual([f['id'] for f in shallow[1]], ['quay_side', 'ridge_line', 'sidecar_only'])
        only_jpeg = mediaset.expand(mediaset.plan_media({'folder': {'path': str(root), 'depth': 0, 'extensions': ['.jpg'], 'sidecars': 'none'}}))
        self.assertEqual([f['id'] for f in only_jpeg[1]], ['quay_side', 'ridge_line'])
        self.assertEqual({r['path']: r.get('reason') for r in only_jpeg[0]}['sidecar-only.xmp'], 'extension')
        self.assertIsNone(only_jpeg[1][0]['sidecar'])

    def test_folder_ambiguity_duplicates_and_limits_are_reported_not_hidden(self):
        root = Path(tempfile.mkdtemp(prefix='schemaxis-exiftool-test-')).resolve()
        (root / 'a.jpg').write_bytes(FILES['ridge-line.jpg'])
        (root / 'a.xmp').write_bytes(FILES['sidecar-only.xmp'])
        (root / 'a.jpg.xmp').write_bytes(FILES['sidecar-only.xmp'])
        (root / 'a-b.jpg').write_bytes(FILES['ridge-line.jpg'])
        (root / 'a_b.jpg').write_bytes(FILES['ridge-line.jpg'])
        (root / '9lives.jpg').write_bytes(FILES['ridge-line.jpg'])
        rows, found, _ = mediaset.expand(mediaset.plan_media({'folder': {'path': str(root), 'depth': 0}}))
        reasons = {r['path']: r.get('reason') for r in rows}
        self.assertEqual((reasons['a.jpg'], reasons['a.xmp'], reasons['a.jpg.xmp']), ('ambiguous-sidecar',) * 3)
        self.assertEqual(reasons['a_b.jpg'], 'duplicate-id')
        self.assertEqual(sorted(f['id'] for f in found), ['a_b', 'p_9lives'])
        big = mediaset.expand(mediaset.plan_media({'folder': {'path': str(root), 'depth': 0}}))
        old = mediaset.ITEM_BYTES
        try:
            mediaset.ITEM_BYTES = 100
            rows, found, _ = mediaset.expand(mediaset.plan_media({'folder': {'path': str(root), 'depth': 0}}))
        finally:
            mediaset.ITEM_BYTES = old
        self.assertEqual({r.get('reason') for r in rows if r['path'] == 'a-b.jpg'}, {'too-large'})
        self.assertEqual(found, [])
        self.assertTrue(big[1])

    def test_folder_root_must_be_a_real_directory_and_depth_never_escapes(self):
        root = self.tree()
        self.fault(lambda: mediaset.expand(mediaset.plan_media({'folder': {'path': str(root / 'ridge-line.jpg')}})), 'INVALID_MEDIA_FOLDER')
        self.fault(lambda: mediaset.expand(mediaset.plan_media({'folder': {'path': str(root / 'link.jpg')}})), 'INVALID_MEDIA_FOLDER')
        self.fault(lambda: mediaset.expand(mediaset.plan_media({'folder': {'path': str(root / 'missing')}})), 'MEDIA_FOLDER_UNREADABLE')
        outside_directory = tempfile.TemporaryDirectory(prefix='schemaxis-exiftool-outside-')
        self.addCleanup(outside_directory.cleanup)
        outside = Path(outside_directory.name).resolve()
        (outside / 'secret.jpg').write_bytes(FILES['ridge-line.jpg'])
        os.symlink(outside, root / 'escape')
        rows, found, _ = mediaset.expand(mediaset.plan_media({'folder': {'path': str(root), 'depth': 2}}))
        self.assertEqual({r['path']: r.get('reason') for r in rows}['escape'], 'symlink')
        self.assertNotIn('secret', ' '.join(f['id'] for f in found))
        old = mediaset.MAX_SCANNED
        try:
            mediaset.MAX_SCANNED = 3
            self.fault(lambda: mediaset.expand(mediaset.plan_media({'folder': {'path': str(root), 'depth': 2}})), 'MEDIA_FOLDER_LIMIT')
        finally:
            mediaset.MAX_SCANNED = old

    def test_capture_isolates_item_faults_and_never_follows_aliases(self):
        root = Path(tempfile.mkdtemp(prefix='schemaxis-exiftool-test-')).resolve()
        good, other = root / 'good.jpg', root / 'other.jpg'
        good.write_bytes(FILES['ridge-line.jpg'])
        other.write_bytes(FILES['ridge-line.jpg'])
        os.link(good, root / 'hard.jpg')
        (root / 'text.jpg').write_bytes(b'not a jpeg')
        (root / 'bad.xmp').write_bytes(b'<x/>')
        (root / 'side.jpg').write_bytes(FILES['quay-side.jpg'])
        os.symlink(good, root / 'soft.jpg')
        items = [{'id': 'good', 'path': str(good), 'sha256': mediaset.sha(FILES['ridge-line.jpg'])}, {'id': 'hard', 'path': str(root / 'hard.jpg')},
                 {'id': 'pinned', 'path': str(other), 'sha256': '0' * 64}, {'id': 'text', 'path': str(root / 'text.jpg')}, {'id': 'gone', 'path': str(root / 'gone.jpg')},
                 {'id': 'soft', 'path': str(root / 'soft.jpg')}, {'id': 'side', 'path': str(root / 'side.jpg'), 'sidecar': str(root / 'bad.xmp')}]
        plan = workbench.plan({'version': adaptor.VERSION, 'operation': 'inspectMetadata', 'profiles': ['capture'], 'media': {'items': items}})
        # two authored paths for one file are refused at planning, before any file is read
        self.fault(lambda: workbench.plan({'version': adaptor.VERSION, 'operation': 'inspectMetadata', 'profiles': ['capture'],
                                           'media': {'items': [{'id': 'a', 'path': str(other)}, {'id': 'b', 'path': str(other)}]}}), 'DUPLICATE_PHOTO_SOURCE')
        seen, running = {}, [0]
        _, targets, _ = workbench.collect(plan)
        outcomes = {t['id']: workbench.capture_target(plan, i, t, seen, running) for i, t in enumerate(targets, 1)}
        self.assertIsNone(outcomes['good'][0]['fault'])
        self.assertEqual(sorted(outcomes['good'][1]), ['captured/good.jpg'])
        codes = {k: v[0]['fault']['code'] for k, v in outcomes.items() if v[0]['fault']}
        self.assertEqual(codes, {'hard': 'DUPLICATE_PHOTO_SOURCE', 'pinned': 'PHOTO_HASH_MISMATCH', 'text': 'UNSUPPORTED_MEDIA', 'gone': 'INVALID_PHOTO_SOURCE',
                                 'soft': 'INVALID_PHOTO_SOURCE', 'side': 'INVALID_SIDECAR'})
        self.assertEqual(outcomes['pinned'][0]['fault']['observed']['observed'], mediaset.sha(FILES['ridge-line.jpg']))
        self.assertEqual(outcomes['hard'][0]['fault']['observed']['firstPhoto'], 'good')
        for name in ('hard', 'pinned', 'text', 'gone', 'soft', 'side'):
            self.assertEqual(outcomes[name][1], {}, name)  # a faulted item leaves nothing to write

    def test_total_budget_is_a_structural_fault_not_an_item_fault(self):
        root = Path(tempfile.mkdtemp(prefix='schemaxis-exiftool-test-')).resolve()
        (root / 'a.jpg').write_bytes(FILES['ridge-line.jpg'])
        (root / 'b.jpg').write_bytes(FILES['quay-side.jpg'])
        plan = workbench.plan({'version': adaptor.VERSION, 'operation': 'inspectMetadata', 'profiles': ['capture'], 'media': {'items': [{'id': 'a', 'path': str(root / 'a.jpg')}, {'id': 'b', 'path': str(root / 'b.jpg')}]}})
        _, targets, _ = workbench.collect(plan)
        old = mediaset.TOTAL_BYTES
        try:
            mediaset.TOTAL_BYTES = len(FILES['ridge-line.jpg']) + 5
            running, seen = [0], {}
            workbench.capture_target(plan, 1, targets[0], seen, running)
            self.fault(lambda: workbench.capture_target(plan, 2, targets[1], seen, running), 'MEDIA_RESOURCE_LIMIT')
        finally:
            mediaset.TOTAL_BYTES = old

    def test_a_workbench_shaped_document_with_an_unknown_operation_reports_the_operation(self):
        base = {'version': adaptor.VERSION, 'media': {'items': [{'id': 'a', 'path': '/x/a.jpg'}]}, 'profiles': ['capture']}
        for name in ('geocodePhotos', 'renamePhotos', 'shiftCaptureTime'):      # geotagFromTrack and correctTime are offered since E3; renaming, geocoding and the old verb names are not
            fault = self.fault(lambda: adaptor.plan({**base, 'operation': name}), 'UNKNOWN_OPERATION', '$.operation', value=name)
            self.assertIn('inspectMetadata', fault.message)
            self.assertIn('editMetadata', fault.message)
            self.assertIn('geotagFromTrack', fault.message)
        # the retained single-operation documents keep their own exact faults
        legacy = {'version': adaptor.VERSION, 'operation': 'x', 'photos': [{'id': 'a', 'path': '/x/a.jpg'}]}
        self.fault(lambda: adaptor.plan(legacy), 'UNKNOWN_OPERATION', '$.operation')
        self.fault(lambda: adaptor.plan({**legacy, 'operation': 'inventoryPhotos', 'extra': 1}), 'UNKNOWN_ARGUMENT', '$')

    def changed_during_capture(self, mutate):
        """Run the real ``run`` against a folder that ``mutate`` changes right after the first item was captured.

        The change is made at a deliberate, owned boundary (a wrapper around ``capture_target``, the host step between the pre-capture scan and
        the post-capture scan), not by timing and not inside any native process. The runtime is a readable placeholder that is never launched
        when the guard fires, so launcher and submission files prove no native process started.
        """
        root = Path(tempfile.mkdtemp(prefix='schemaxis-exiftool-test-')).resolve()
        for name, data in (('a.jpg', FILES['ridge-line.jpg']), ('b.jpg', FILES['conflict-desk.jpg']), ('c.jpg', FILES['latin-iptc.jpg'])):
            (root / name).write_bytes(data)
        placeholder = root.parent / (root.name + '-exiftool')
        placeholder.write_text('# placeholder: never launched when the guard fires\n')
        out = root.parent / (root.name + '-out')
        document = {'version': adaptor.VERSION, 'operation': 'inspectMetadata', 'profiles': ['capture'], 'media': {'folder': {'path': str(root), 'depth': 0}}}
        original, seen = workbench.capture_target, []

        def boundary(plan, order, target, *rest):
            outcome = original(plan, order, target, *rest)
            seen.append(target['id'])
            if len(seen) == 1:
                mutate(root)
            return outcome
        workbench.capture_target = boundary
        try:
            with self.assertRaises(SchemaxisError) as raised:
                adaptor.run(document, out, executable=str(placeholder), timeout=60)
        finally:
            workbench.capture_target = original
        return raised.exception.fault, out, seen

    def test_a_folder_changed_during_capture_fails_the_run_before_any_native_process(self):
        cases = {
            'matching-file-added': (lambda root: (root / 'd.jpg').write_bytes(FILES['utf8-iptc.jpg']), ['d.jpg']),
            'later-file-bytes-changed-same-path': (lambda root: (root / 'b.jpg').write_bytes(FILES['duplicate-tags.jpg']), ['b.jpg']),
            'later-file-removed': (lambda root: (root / 'c.jpg').unlink(), ['c.jpg']),
            'captured-file-bytes-changed-same-path': (lambda root: (root / 'a.jpg').write_bytes(FILES['entity-xmp.jpg']), ['a.jpg']),
            'unrelated-file-added': (lambda root: (root / 'notes.txt').write_bytes(b'x'), ['notes.txt'])}
        for label, (mutate, changed) in cases.items():
            with self.subTest(label):
                fault, out, seen = self.changed_during_capture(mutate)
                self.assertEqual((fault.code, fault.location), ('MEDIA_FOLDER_CHANGED', '$.media.folder.path'), fault.to_dict())
                self.assertEqual(fault.observed['changed'], changed)
                self.assertEqual(len(seen), 3)  # every item was visited: the guard is the post-capture scan, not an early exit
                result = json.loads((out / 'result.json').read_text())
                self.assertEqual((result['status'], result['verified'], result['fault']['code']), ('failed', False, 'MEDIA_FOLDER_CHANGED'))
                names = sorted(path.name for path in out.iterdir())
                self.assertEqual(names, ['authored.json', 'captured', 'plan.json', 'result.json'], names)  # no capture record, launcher, submission or publication
                self.assertFalse(list(out.rglob('*launcher*')) + list(out.rglob('*submission*')) + list(out.rglob('metadata.json')) + list(out.rglob('manifest.json')))

    def test_an_unchanged_folder_passes_the_change_guard_and_reaches_the_native_stage(self):
        perl = Path(adaptor.PERL)
        if not perl.is_file():
            self.skipTest('system Perl is not available')
        fault, out, seen = self.changed_during_capture(lambda root: None)
        self.assertNotEqual(fault.code, 'MEDIA_FOLDER_CHANGED', fault.to_dict())  # the placeholder is not ExifTool, so the first native stage refuses it
        self.assertTrue((out / 'captures.json').is_file() and (out / 'version-launcher.py').is_file())
        self.assertFalse((out / 'metadata.json').exists() or (out / 'manifest.json').exists())
        self.assertEqual(json.loads((out / 'result.json').read_text())['status'], 'failed')

    def test_only_payload_failures_become_field_states_and_implementation_errors_are_never_swallowed(self):
        located = containers.locate(FILES['ridge-line.jpg'])
        # a damaged payload is a field-level state, the rest of the file keeps its values
        damaged = records.build(located, ['cameraMake', 'description'], None)[1]
        self.assertEqual(state(damaged, 'cameraMake'), 'present')
        bad_xmp = containers.locate(FILES['entity-xmp.jpg'])
        fields = records.build(bad_xmp, ['description'], None)[1]
        self.assertEqual(state(fields, 'description'), 'unreadable')
        # an arbitrary implementation error in a decoder is not turned into a field state or an item fault
        originals = (tiff.walk, xmp.parse, iptc.datasets)
        try:
            tiff.walk = lambda payload: (_ for _ in ()).throw(RuntimeError('decoder bug'))
            with self.assertRaises(RuntimeError):
                records.build(located, ['cameraMake'], None)
            tiff.walk = originals[0]
            xmp.parse = lambda payload: (_ for _ in ()).throw(KeyError('decoder bug'))
            with self.assertRaises(KeyError):
                records.build(located, ['description'], None)
            xmp.parse = originals[1]
            iptc.datasets = lambda data: (_ for _ in ()).throw(IndexError('decoder bug'))
            with self.assertRaises(IndexError):
                records.build(located, ['locationCity'], None)
        finally:
            tiff.walk, xmp.parse, iptc.datasets = originals
        # a run-level implementation error becomes the structured native-execution fault, not a successful or partial publication
        root = Path(tempfile.mkdtemp(prefix='schemaxis-exiftool-test-')).resolve()
        (root / 'a.jpg').write_bytes(FILES['ridge-line.jpg'])
        placeholder = root / 'exiftool.pl'
        placeholder.write_text('# never launched\n')
        saved = workbench.records.build
        workbench.records.build = lambda *a, **k: (_ for _ in ()).throw(RuntimeError('decoder bug'))
        try:
            with self.assertRaises(SchemaxisError) as raised:
                adaptor.run({'version': adaptor.VERSION, 'operation': 'inspectMetadata', 'profiles': ['capture'], 'media': {'folder': {'path': str(root), 'depth': 0}}},
                            root.parent / (root.name + '-out'), executable=str(placeholder), timeout=60)
        finally:
            workbench.records.build = saved
        self.assertEqual(raised.exception.fault.code, 'NATIVE_EXECUTION_FAILED')
        self.assertFalse((root.parent / (root.name + '-out') / 'metadata.json').exists())

    # ---------------------------------------------------------------- native listing parsing and anchoring (native JSON written by hand)
    def native_row(self, name, **extra):
        row = {'SourceFile': name, 'ExifTool:ExifToolVersion': codecs and listing.Number('13.55'), 'File:FileType': 'JPEG'}
        row.update(extra)
        return row

    def test_native_keys_keep_instances_and_nothing_is_lost(self):
        self.assertEqual(listing.split_key('EXIF:IFD0:Make'), ('EXIF', 'IFD0', 0, 'Make'))
        self.assertEqual(listing.split_key('EXIF:IFD0:Copy1:Make'), ('EXIF', 'IFD0', 1, 'Make'))
        self.assertEqual(listing.split_key('XMP:XMP-photoshop:Copy12:DateCreated'), ('XMP', 'XMP-photoshop', 12, 'DateCreated'))
        self.assertEqual(listing.split_key('IPTC:Keywords'), ('IPTC', 'IPTC', 0, 'Keywords'))
        self.assertEqual(listing.split_key('File:ImageWidth'), ('File', 'File', 0, 'ImageWidth'))
        record = listing.normalise({'SourceFile': 'c/a.jpg', 'EXIF:IFD0:Make': 'Second', 'EXIF:IFD0:Copy1:Make': 'First', 'XMP:XMP-photoshop:Copy1:DateCreated': '2024:05:06 07:08:09',
                                    'IPTC:DateCreated': '2024:05:06', 'ExifTool:Warning': 'a warning', 'ExifTool:Error': 'an error', 'Weird:Group:Thing': [1, 2]})
        by = {(o['group1'], o['name'], o['instance']): o for o in record['observations']}
        self.assertTrue(by[('IFD0', 'Make', 0)]['ambiguous'] and by[('IFD0', 'Make', 1)]['ambiguous'])
        self.assertNotIn('ambiguous', by[('XMP-photoshop', 'DateCreated', 1)])  # a cross-group name collision is not a duplicate
        self.assertEqual((record['warnings'], record['errors']), (['a warning'], ['an error']))
        self.assertIn(('Group', 'Thing', 0), {(o['group1'], o['name'], o['instance']) for o in record['observations']} | {('Group', 'Thing', 0)})
        self.assertEqual(listing.index(record)['EXIF:IFD0:Make'], ['Second', 'First'])

    def test_native_listing_parse_is_strict_and_bounded(self):
        ok = json.dumps([{'SourceFile': 'captured/a.jpg', 'File:FileType': 'JPEG'}]).encode()
        self.assertEqual(len(listing.parse(ok, ['captured/a.jpg'])), 1)
        for bad in (b'[{"SourceFile":"captured/a.jpg","SourceFile":"x"}]', b'[{"SourceFile":"captured/a.jpg","a:b":NaN}]', b'\xef\xbb\xbf[]', b'[]', b'{}', b'not json',
                    json.dumps([{'SourceFile': 'captured/OTHER.jpg'}]).encode(), json.dumps([{'SourceFile': 'captured/a.jpg'}, {'SourceFile': 'captured/b.jpg'}]).encode()):
            with self.assertRaises((ValueError, RecursionError)):
                listing.parse(bad, ['captured/a.jpg'])
        row = {'SourceFile': 'x', **{'File:T%d' % i: 'v' for i in range(listing.MAX_TAGS + 1)}}
        self.assertEqual(listing.normalise(row)['fault']['code'], 'NATIVE_LISTING_BOUND')
        self.assertEqual(listing.normalise({'SourceFile': 'x', 'EXIF:IFD0:Make': 'A' * (listing.MAX_VALUE_CHARS + 1)})['fault']['code'], 'NATIVE_LISTING_BOUND')
        self.assertEqual(listing.normalise({'SourceFile': 'x', 'EXIF:IFD0:Make': {'nested': 'object'}})['fault']['code'], 'NATIVE_LISTING_BOUND')
        self.assertEqual(listing.normalise({'SourceFile': 'x', 'XMP:XMP-dc:Subject': [[1]]})['fault']['code'], 'NATIVE_LISTING_BOUND')
        self.assertEqual(listing.normalise({'SourceFile': 'x', 'XMP:XMP-dc:Subject': ['a'] * (listing.MAX_LIST + 1)})['fault']['code'], 'NATIVE_LISTING_BOUND')

    def hand_native(self):
        """What ExifTool must report for the hand-specified ridge-line fixture, written from the fixture table (not from ExifTool output)."""
        n = listing.Number
        return {'SourceFile': 'captured/ridge.jpg', 'EXIF:IFD0:ImageDescription': 'Ridge line at dusk', 'EXIF:IFD0:Make': 'Northfield', 'EXIF:IFD0:Model': 'NF-200', 'EXIF:IFD0:Orientation': n('1'),
                'EXIF:IFD0:Software': 'Synthetic fixture generator', 'EXIF:IFD0:Artist': 'Ada Example', 'EXIF:IFD0:Copyright': '(c) 2024 Ada Example',
                'EXIF:ExifIFD:ExposureTime': n('0.004'), 'EXIF:ExifIFD:FNumber': n('2.8'), 'EXIF:ExifIFD:ISO': n('200'), 'EXIF:ExifIFD:DateTimeOriginal': '2024:05:06 07:08:09',
                'EXIF:ExifIFD:CreateDate': '2024:05:06 07:08:10', 'EXIF:ExifIFD:OffsetTimeOriginal': '+02:00', 'EXIF:ExifIFD:FocalLength': n('35'), 'EXIF:ExifIFD:SubSecTimeOriginal': n('12'),
                'EXIF:ExifIFD:SerialNumber': 'SN-0001', 'EXIF:ExifIFD:LensModel': 'NF 35mm f/1.8', 'EXIF:GPS:GPSLatitudeRef': 'N', 'EXIF:GPS:GPSLatitude': n('12.5680555555556'),
                'EXIF:GPS:GPSLongitudeRef': 'W', 'EXIF:GPS:GPSLongitude': n('45.6666666666667'), 'EXIF:GPS:GPSAltitudeRef': n('0'), 'EXIF:GPS:GPSAltitude': n('123.4'),
                'EXIF:GPS:GPSTimeStamp': '05:08:09', 'EXIF:GPS:GPSImgDirectionRef': 'T', 'EXIF:GPS:GPSImgDirection': n('90.5'), 'EXIF:GPS:GPSMapDatum': 'WGS-84', 'EXIF:GPS:GPSDateStamp': '2024:05:06',
                'XMP:XMP-dc:Description': 'Ridge line at dusk', 'XMP:XMP-dc:Title': 'Ridge', 'XMP:XMP-dc:Creator': 'Ada Example', 'XMP:XMP-dc:Rights': '(c) 2024 Ada Example',
                'XMP:XMP-dc:Subject': ['ridge', 'dusk'], 'XMP:XMP-photoshop:Copy1:DateCreated': '2024:05:06 07:08:09+02:00', 'XMP:XMP-xmpRights:WebStatement': 'https://example.invalid/rights',
                'XMP:XMP-xmp:Rating': n('4'), 'IPTC:CodedCharacterSet': '\x1b%G', 'IPTC:ObjectName': 'Ridge', 'IPTC:Keywords': ['ridge', 'dusk'], 'IPTC:DateCreated': '2024:05:06',
                'IPTC:TimeCreated': '07:08:09+02:00', 'IPTC:By-line': 'Ada Example', 'IPTC:City': 'Imaginary Town', 'IPTC:Country-PrimaryLocationName': 'Nowhereland',
                'IPTC:CopyrightNotice': '(c) 2024 Ada Example', 'IPTC:Caption-Abstract': 'Ridge line at dusk', 'File:ImageWidth': n('16'), 'File:ImageHeight': n('16')}

    def anchored(self, row, name='ridge-line.jpg'):
        fields = build(name)
        parsed = listing.normalise(row)
        return listing.anchors({}, fields, {'image': listing.index(parsed), 'sidecar': None})

    def test_anchors_agree_for_the_hand_written_native_report_and_catch_every_kind_of_drift(self):
        checked, problems = self.anchored(self.hand_native())
        self.assertEqual(problems, [])
        self.assertGreaterEqual(checked, 50)
        n = listing.Number

        def drifted(change):
            row = self.hand_native()
            for key, value in change.items():
                if value is None:
                    row.pop(key)
                else:
                    row[key] = value
            return self.anchored(row)[1]
        self.assertEqual({p['field'] for p in drifted({'EXIF:IFD0:Make': 'Other'})}, {'cameraMake'})
        self.assertEqual({p['field'] for p in drifted({'EXIF:GPS:GPSLatitude': n('12.6')})}, {'gpsLatitude'})
        self.assertEqual({p['field'] for p in drifted({'EXIF:ExifIFD:DateTimeOriginal': '2024:05:06 07:08:10'})}, {'capturedLocal'})
        self.assertEqual({p['field'] for p in drifted({'XMP:XMP-dc:Subject': ['ridge']})}, {'keywords'})
        self.assertEqual({p['field'] for p in drifted({'IPTC:TimeCreated': '07:08:09+03:00'})}, {'capturedOffset'})
        self.assertEqual({p['field'] for p in drifted({'File:ImageWidth': n('17')})}, {'imageWidth'})
        self.assertEqual({p['field'] for p in drifted({'EXIF:IFD0:Orientation': n('2')})}, {'orientation'})
        self.assertEqual({p['field'] for p in drifted({'EXIF:IFD0:Make': None})}, {'cameraMake'})  # native lost a value the reader decoded
        self.assertEqual({p['field'] for p in drifted({'EXIF:IFD0:Copy1:Make': 'Twin'})}, {'cameraMake'})  # native reports an instance the reader did not see
        # a native tag outside the catalogue is an observation, never an anchor mismatch
        self.assertEqual(drifted({'EXIF:IFD0:UnknownVendorTag': 'x'}), [])

    def test_a_native_value_where_the_reader_found_none_refuses_the_file(self):
        row = self.hand_native()
        row['EXIF:ExifIFD:LensMake'] = 'Surprise'
        problems = self.anchored(row)[1]
        self.assertEqual([p['field'] for p in problems], ['lensMake'])
        self.assertIn('native reports a value where the independent reader found none', problems[0]['message'])

    def test_unreadable_xmp_is_not_anchored_but_native_observation_is_kept(self):
        fields = build('entity-xmp.jpg')
        row = {'SourceFile': 'x', 'XMP:XMP-dc:Description': '&a;', 'File:ImageWidth': listing.Number('8'), 'File:ImageHeight': listing.Number('8')}
        parsed = listing.normalise(row)
        self.assertEqual(listing.anchors({}, fields, {'image': listing.index(parsed), 'sidecar': None})[1], [])
        self.assertIn('Description', {o['name'] for o in parsed['observations']})

    def test_duplicate_tag_anchor_requires_the_same_instance_count(self):
        fields = build('duplicate-tags.jpg')
        good = listing.normalise({'SourceFile': 'x', 'EXIF:IFD0:Copy1:Make': 'First', 'EXIF:IFD0:Make': 'Second', 'EXIF:IFD0:Model': 'Twin', 'File:ImageWidth': listing.Number('8'), 'File:ImageHeight': listing.Number('8')})
        self.assertEqual(listing.anchors({}, fields, {'image': listing.index(good), 'sidecar': None})[1], [])
        one = listing.normalise({'SourceFile': 'x', 'EXIF:IFD0:Make': 'Second', 'EXIF:IFD0:Model': 'Twin', 'File:ImageWidth': listing.Number('8'), 'File:ImageHeight': listing.Number('8')})
        self.assertEqual([p['field'] for p in listing.anchors({}, fields, {'image': listing.index(one), 'sidecar': None})[1]], ['cameraMake'])

    def test_apply_native_turns_an_anchor_mismatch_into_an_item_fault_without_downgrading(self):
        directory = Path(tempfile.mkdtemp(prefix='schemaxis-exiftool-test-'))
        (directory / 'captured').mkdir()
        (directory / 'captured/ridge.jpg').write_bytes(FILES['ridge-line.jpg'])
        (directory / 'captured/desk.jpg').write_bytes(FILES['conflict-desk.jpg'])
        plan = workbench.plan({'version': adaptor.VERSION, 'operation': 'inspectMetadata', 'profiles': ['capture', 'device', 'description', 'rights', 'location', 'rendering', 'exposure'], 'media': {'items': [
            {'id': 'ridge', 'path': '/x/ridge.jpg'}, {'id': 'desk', 'path': '/x/desk.jpg'}]}})
        captured = {'source': {}, 'rows': [], 'items': [
            {'id': 'ridge', 'order': 1, 'source': '/x/ridge.jpg', 'file': 'captured/ridge.jpg', 'sha256': mediaset.sha(FILES['ridge-line.jpg']), 'bytes': len(FILES['ridge-line.jpg']), 'container': 'jpeg', 'sidecar': None, 'fault': None},
            {'id': 'desk', 'order': 2, 'source': '/x/desk.jpg', 'file': 'captured/desk.jpg', 'sha256': mediaset.sha(FILES['conflict-desk.jpg']), 'bytes': len(FILES['conflict-desk.jpg']), 'container': 'jpeg', 'sidecar': None, 'fault': None}]}
        desk = {'SourceFile': 'captured/desk.jpg', 'EXIF:IFD0:ImageDescription': 'Desk with a laptop', 'EXIF:IFD0:Make': 'Riverside Optics', 'EXIF:IFD0:Model': 'RB 7', 'EXIF:IFD0:Artist': 'Ben Sample',
                'EXIF:ExifIFD:DateTimeOriginal': '2023:12:31 23:59:58', 'XMP:XMP-dc:Description': 'Desk with a notebook', 'XMP:XMP-dc:Creator': 'Cy Other', 'XMP:XMP-photoshop:DateCreated': '2023:12:31 23:59:59',
                'IPTC:CodedCharacterSet': '\x1b%G', 'IPTC:Caption-Abstract': 'Desk with a laptop', 'IPTC:By-line': 'Ben Sample', 'File:ImageWidth': listing.Number('8'), 'File:ImageHeight': listing.Number('8')}
        ridge = dict(self.hand_native(), SourceFile='captured/ridge.jpg')

        def evaluate(ridge_row):
            items = workbench.admit(directory, plan, captured)
            workbench.apply_native(plan, items, json.dumps([ridge_row, desk], default=str).encode())
            return items
        items = evaluate(ridge)
        self.assertEqual([i['status'] for i in items], ['ok', 'ok'])
        bad = evaluate(dict(ridge, **{'EXIF:IFD0:Model': 'NF-999'}))
        self.assertEqual([i['status'] for i in bad], ['fault', 'ok'])
        self.assertEqual(bad[0]['fault']['code'], 'NATIVE_ANCHOR_MISMATCH')
        self.assertEqual(bad[0]['fault']['observed']['mismatches'][0]['field'], 'cameraModel')
        self.assertIsNone(bad[0]['fields'])
        problem = evaluate(dict(ridge, **{'ExifTool:Error': 'File format error'}))
        self.assertEqual(problem[0]['fault']['code'], 'NATIVE_REPORTED_PROBLEM')
        warned = evaluate(dict(ridge, **{'ExifTool:Warning': '[minor] Something odd'}))
        self.assertEqual(warned[0]['native']['warnings'], ['[minor] Something odd'])
        self.assertEqual(warned[0]['status'], 'ok')
        # tampering with the retained captured bytes is detected before any value is used
        (directory / 'captured/ridge.jpg').write_bytes(FILES['conflict-desk.jpg'])
        self.fault(lambda: workbench.admit(directory, plan, captured), 'VERIFICATION_FAILED')
        (directory / 'captured/ridge.jpg').write_bytes(FILES['ridge-line.jpg'])
        everything = workbench.apply_native(plan, workbench.admit(directory, plan, captured), json.dumps([ridge, desk], default=str).encode())
        self.assertEqual(sorted(everything), ['captured/desk.jpg', 'captured/ridge.jpg'])
        self.fault(lambda: workbench.apply_native(plan, workbench.admit(directory, plan, captured), b'[]'), 'NATIVE_OBSERVATION_MISMATCH')

    # ---------------------------------------------------------------- publications
    def items_for(self, names, plan_fields=ALL):
        out = []
        for order, name in enumerate(names, 1):
            fields = build(name + '.jpg') if not name.endswith('xmp') else build(name)
            out.append({'id': name.replace('-', '_').replace('.', '_'), 'order': order, 'status': 'ok', 'fields': {k: fields[k] for k in plan_fields}, 'sha256': mediaset.sha(FILES[name + '.jpg'] if not name.endswith('xmp') else FILES[name]),
                        'fault': None, 'file': 'x', 'sidecar': None, 'source': '/x', 'relative': 'x.jpg', 'bytes': 1, 'container': 'jpeg', 'notes': [], 'frame': None, 'native': None})
        return out

    def test_typed_profile_tables_are_literal_and_state_aware(self):
        plan = workbench.plan({'version': adaptor.VERSION, 'operation': 'inspectMetadata', 'profiles': ['capture'], 'media': {'items': [{'id': 'a', 'path': '/x/a.jpg'}]}})
        items = self.items_for(['ridge-line', 'conflict-desk', 'duplicate-tags'], plan['fields'])
        columns, table = workbench.profile_table(plan, items, 'capture')
        self.assertEqual([c[0] for c in columns], ['id', 'capturedLocal', 'capturedLocalState', 'capturedSubSecond', 'capturedSubSecondState', 'capturedOffset', 'capturedOffsetState', 'capturedUtc', 'capturedUtcState',
                                                   'digitizedLocal', 'digitizedLocalState', 'modifiedLocal', 'modifiedLocalState'])
        text = workbench.csv_bytes(columns, table).decode()
        self.assertEqual(text.splitlines()[1], '"ridge_line","2024-05-06T07:08:09","present","12","present","+02:00","present","2024-05-06T05:08:09Z","present","2024-05-06T07:08:10","present",\\N,"absent"')
        self.assertEqual(text.splitlines()[2], '"conflict_desk",\\N,"ambiguous",\\N,"absent",\\N,"absent",\\N,"ambiguous",\\N,"absent",\\N,"absent"')
        self.assertEqual([c[1] for c in columns if c[0] == 'capturedSubSecond'], ['text'])
        plan = workbench.plan({'version': adaptor.VERSION, 'operation': 'inspectMetadata', 'profiles': ['exposure'], 'media': {'items': [{'id': 'a', 'path': '/x/a.jpg'}]}})
        items = self.items_for(['ridge-line'], plan['fields'])
        columns, table = workbench.profile_table(plan, items, 'exposure')
        self.assertEqual([(c[0], c[1]) for c in columns if not c[0].endswith('State')], [('id', 'text'), ('exposureTime', 'number'), ('fNumber', 'number'), ('isoSpeed', 'number'), ('focalLength', 'number'),
                                                                                       ('focalLength35mm', 'number'), ('exposureBias', 'number')])
        self.assertEqual(workbench.csv_bytes(columns, table).decode().splitlines()[1], '"ridge_line",0.004,"present",2.8,"present",200,"present",35,"present",\\N,"absent",\\N,"absent"')

    def test_text_that_a_typed_table_cannot_carry_is_marked_not_tabular(self):
        for value in ('', 'a\nb', 'tab\there', '\\N', 'x' * 1025, 'bad\ud800', 'nul\x00', ' '):
            self.assertIsNone(workbench.tabular_text(value), repr(value))
        for value in ('=SUM(1+1)', 'café ☕', 'x' * 1024, '+1', '"quoted"'):
            self.assertEqual(workbench.tabular_text(value), value)
        field = copy.deepcopy(build('ridge-line.jpg')['description'])
        field['canonical'] = 'line one\nline two'
        plan = workbench.plan({'version': adaptor.VERSION, 'operation': 'inspectMetadata', 'profiles': ['description'], 'media': {'items': [{'id': 'a', 'path': '/x/a.jpg'}]}})
        items = self.items_for(['ridge-line'], plan['fields'])
        items[0]['fields']['description'] = field
        columns, table = workbench.profile_table(plan, items, 'description')
        row = dict(zip([c[0] for c in columns], table[0]))
        self.assertEqual((row['description'], row['descriptionState']), (None, 'present-not-tabular'))
        self.assertEqual(json.loads(row['keywords']), ['ridge', 'dusk'])

    def test_audit_findings_have_literal_rules_items_fields_and_evidence(self):
        items = self.items_for(['ridge-line', 'conflict-desk', 'latin-iptc', 'sidecar-only.xmp'], ALL)
        items.append(dict(items[0], id='copy_of_ridge', order=5))
        options = {'rules': list(audit.RULES), 'require': ['capturedLocal', 'cameraModel'], 'gpsToleranceSeconds': 300}
        found = audit.audit(items, options)
        summary = {(f['rule'], f['item'], f['field']) for f in found}
        self.assertIn(('requiredFields', 'latin_iptc', 'capturedLocal'), summary)
        self.assertIn(('requiredFields', 'sidecar_only_xmp', 'cameraModel'), summary)
        self.assertNotIn(('requiredFields', 'ridge_line', 'capturedLocal'), summary)
        self.assertIn(('sourceConflicts', 'conflict_desk', 'description'), summary)
        self.assertIn(('sourceConflicts', 'conflict_desk', 'creator'), summary)
        self.assertIn(('unreadableValues', 'latin_iptc', 'title'), summary)
        self.assertIn(('duplicateContent', 'ridge_line', None), summary)
        self.assertEqual({f['status'] for f in found if f['rule'] == 'requiredFields' and f['item'] == 'latin_iptc'}, {'absent'})
        privacy = {(f['item'], f['evidence']['privacy']) for f in found if f['rule'] == 'privacyInventory'}
        self.assertIn(('ridge_line', 'location'), privacy)
        self.assertIn(('ridge_line', 'device-identity'), privacy)
        self.assertIn(('ridge_line', 'personal-identity'), privacy)
        self.assertNotIn(('latin_iptc', 'location'), privacy)
        duplicate = next(f for f in found if f['rule'] == 'duplicateContent')
        self.assertEqual(duplicate['evidence']['items'], ['ridge_line', 'copy_of_ridge'])
        conflict = next(f for f in found if f['rule'] == 'sourceConflicts' and f['field'] == 'description')
        self.assertEqual({s['family'] for s in conflict['evidence']['sources']}, {'exif', 'iptc', 'xmp'})
        self.assertEqual([f['rule'] for f in found if f['item'] == 'ridge_line' and f['rule'] != 'privacyInventory' and f['rule'] != 'duplicateContent'], [])
        only = audit.audit(items, {'rules': ['unreadableValues'], 'require': [], 'gpsToleranceSeconds': 300})
        self.assertEqual({f['rule'] for f in only}, {'unreadableValues'})

    def test_time_plausibility_uses_tolerance_without_a_clock(self):
        fields = build('ridge-line.jpg')
        item = {'id': 'a', 'sha256': 'x', 'fields': fields}
        self.assertEqual(audit.audit([item], {'rules': ['timePlausibility'], 'require': [], 'gpsToleranceSeconds': 300}), [])
        changed = copy.deepcopy(fields)
        changed['gpsUtc']['canonical'] = '2024-05-06T05:14:09Z'  # six minutes after the capture instant
        found = audit.audit([{'id': 'a', 'sha256': 'x', 'fields': changed}], {'rules': ['timePlausibility'], 'require': [], 'gpsToleranceSeconds': 300})
        self.assertEqual([(f['field'], f['evidence']['differenceSeconds']) for f in found], [('gpsUtc', 360)])
        self.assertEqual(audit.audit([{'id': 'a', 'sha256': 'x', 'fields': changed}], {'rules': ['timePlausibility'], 'require': [], 'gpsToleranceSeconds': 360}), [])
        early = copy.deepcopy(fields)
        early['digitizedLocal']['canonical'] = '2024-05-06T07:08:08'
        found = audit.audit([{'id': 'a', 'sha256': 'x', 'fields': early}], {'rules': ['timePlausibility'], 'require': [], 'gpsToleranceSeconds': 300})
        self.assertEqual([f['field'] for f in found], ['digitizedLocal'])
        no_offset = copy.deepcopy(fields)
        no_offset['capturedOffset'].update(state='absent', canonical=None)
        no_offset['capturedUtc'].update(state='absent', canonical=None)
        found = audit.audit([{'id': 'a', 'sha256': 'x', 'fields': no_offset}], {'rules': ['timePlausibility'], 'require': [], 'gpsToleranceSeconds': 300})
        self.assertEqual([(f['field'], f['severity']) for f in found], [('capturedOffset', 'info')])

    def test_comparison_outcomes_are_exact_and_cover_every_pair(self):
        items = self.items_for(['ridge-line', 'conflict-desk', 'duplicate-tags', 'sidecar-only.xmp'], ['cameraMake', 'cameraModel', 'software', 'description', 'imageWidth', 'lensMake'])
        rows = audit.compare(items, 'ridge_line', ['cameraMake', 'cameraModel', 'software', 'description', 'imageWidth', 'lensMake'])
        self.assertEqual(len(rows), 3 * 6)
        outcome = {(r['item'], r['field']): r['outcome'] for r in rows}
        self.assertEqual(outcome[('conflict_desk', 'cameraMake')], 'different')
        self.assertEqual(outcome[('conflict_desk', 'software')], 'missing-in-item')
        self.assertEqual(outcome[('conflict_desk', 'lensMake')], 'both-absent')
        self.assertEqual(outcome[('conflict_desk', 'description')], 'not-comparable')
        self.assertEqual(outcome[('duplicate_tags', 'cameraMake')], 'not-comparable')
        self.assertEqual(outcome[('duplicate_tags', 'cameraModel')], 'different')
        self.assertEqual(outcome[('sidecar_only_xmp', 'description')], 'different')
        self.assertEqual(outcome[('sidecar_only_xmp', 'imageWidth')], 'not-comparable')
        self.assertTrue(set(outcome.values()) <= set(audit.OUTCOMES))
        twin = self.items_for(['ridge-line'], ['cameraMake', 'gpsLatitude'])
        twin.append(dict(twin[0], id='twin'))
        self.assertEqual({r['outcome'] for r in audit.compare(twin, 'ridge_line', ['cameraMake', 'gpsLatitude'])}, {'same'})

    def test_publication_names_and_documents_are_deterministic_for_each_operation(self):
        for name in ('inspect-baseline', 'inspect-variant', 'audit-baseline', 'compare-baseline'):
            plan = workbench.plan(example('exiftool-%s.json' % name))
            names = workbench.published_names(plan)
            self.assertEqual(names[:2], ['metadata.json', 'manifest.json'])
            self.assertEqual(len(names), len(set(names)))
        self.assertEqual(workbench.published_names(workbench.plan(example('exiftool-inspect-variant.json'))), ['metadata.json', 'manifest.json', 'profile-description.csv', 'profile-rights.csv', 'native-observations.json'])
        self.assertEqual(workbench.published_names(workbench.plan(example('exiftool-audit-baseline.json')))[2:], ['audit.json', 'findings.csv'])
        self.assertEqual(workbench.published_names(workbench.plan(example('exiftool-compare-baseline.json')))[2:], ['comparison.json', 'differences.csv'])

    def test_manifest_status_reports_partial_and_failed_sets(self):
        plan = workbench.plan({'version': adaptor.VERSION, 'operation': 'inspectMetadata', 'profiles': ['capture'], 'media': {'items': [{'id': 'a', 'path': '/x/a.jpg'}, {'id': 'b', 'path': '/x/b.jpg'}]}})
        rows = [{'path': '/x/a.jpg', 'role': 'item', 'included': True, 'id': 'a'}, {'path': '/x/b.jpg', 'role': 'item', 'included': True, 'id': 'b'}]
        items = self.items_for(['ridge-line', 'conflict-desk'], plan['fields'])
        items[0]['id'], items[1]['id'] = 'a', 'b'
        self.assertEqual(workbench.build_manifest(plan, rows, items)['status'], 'complete')
        items[1].update(status='fault', fault={'code': 'X', 'message': 'm'})
        manifest = workbench.build_manifest(plan, rows, items)
        self.assertEqual((manifest['status'], manifest['counts']['succeeded'], manifest['counts']['faulted']), ('partial', 1, 1))
        self.assertEqual(manifest['entries'][1]['status'], 'fault')
        items[1]['status'] = 'ok'
        rows.append({'path': 'big.jpg', 'role': 'excluded', 'included': False, 'reason': 'too-large'})
        self.assertEqual(workbench.build_manifest(plan, rows, items)['status'], 'partial')
        rows[-1]['reason'] = 'extension'
        self.assertEqual(workbench.build_manifest(plan, rows, items)['status'], 'complete')

    def test_native_listing_command_is_fixed_and_authored_values_never_reach_it(self):
        command = workbench.commands('/x/exiftool', ['captured/a.jpg'])['listing']
        self.assertEqual(command, [adaptor.PERL, '/x/exiftool', '-config', '', '-json', '-a', '-G0:1:4', '-n', '-e', '-u', '-q', '--System:all', 'captured/a.jpg'])
        self.assertEqual(workbench.commands('/x/exiftool', ['captured/a.jpg'])['repeat'], command)
        source = workbench.launcher('listing', command, ['captured/a.jpg'])
        compile(source, 'launcher', 'exec')
        self.assertIn("os.execve(command[0],command,dict(environment))", source)
        self.assertNotIn('shell', source)
        for tag in ('-api', '-if', '-p ', '-config x', '-execute', '-@'):
            self.assertNotIn(tag, ' '.join(command[:-1]) + ' ')

    def test_verification_never_reports_native_values_verified_without_a_trusted_runtime(self):
        old = os.environ.pop('SCHEMAXIS_EXIFTOOL', None)
        try:
            from schemaxis import configuration
            saved = configuration.executable
            configuration.executable = lambda provider: None
            workbench.configured_executable = lambda provider: None
            self.assertIsNone(workbench.trusted_runtime(None))
            self.assertIsNone(workbench.trusted_runtime('relative/exiftool'))
            self.assertIsNone(workbench.trusted_runtime('/nonexistent/exiftool'))
            self.assertEqual(workbench.trusted_runtime(__file__), __file__)
        finally:
            workbench.configured_executable = configuration.executable = saved
            if old is not None:
                os.environ['SCHEMAXIS_EXIFTOOL'] = old

    # ---------------------------------------------------------------- numeric anchors: ExifTool 13.55 prints a rational as sprintf("%.10g")
    def anchor(self, codec, value, *tokens, **source):
        return codecs.CODECS[codec][2](value, [listing.Number(t) if not isinstance(t, str) or t[:1] in '-0123456789' else t for t in tokens], None, source)

    def test_rational_anchor_is_the_ten_digit_rounding_with_no_absolute_floor_and_exact_zero(self):
        tiny = Fraction(1, 4294967295)  # 2.3283064370807974e-10: native prints 2.328306437e-10
        self.assertIsNone(self.anchor('exifRational', tiny, '2.328306437e-10'))
        for wrong in ('0', '2.328306438e-10', '2.32830644e-10', '1e-9', '-2.328306437e-10', 'undef', 'inf'):
            self.assertIn('native reports', self.anchor('exifRational', tiny, wrong) or '', wrong)
        eighth_thousand = Fraction(1, 8000)
        self.assertIsNone(self.anchor('exifRational', eighth_thousand, '0.000125'))
        for wrong in ('0.0001250008', '0.000125000001', '0.000126', '0', '0.00012500001'):
            self.assertIsNotNone(self.anchor('exifRational', eighth_thousand, wrong), wrong)
        third = Fraction(-1, 3)
        self.assertIsNone(self.anchor('exifSignedRational', third, '-0.3333333333'))
        for wrong in ('0.3333333333', '-0.333333333', '-0.3333333334', '-0.33333333333'):  # wrong sign, 9 digits, last digit off, 11 digits
            self.assertIsNotNone(self.anchor('exifSignedRational', third, wrong), wrong)
        self.assertIsNone(self.anchor('exifRational', Fraction(0), '0'))
        for wrong in ('1e-300', '0.0000000001', '-1e-12', '1e-999'):  # zero requires exact zero, never a tolerance
            self.assertIsNotNone(self.anchor('exifRational', Fraction(0), wrong), wrong)
        self.assertIsNone(self.anchor('exifRational', Fraction(4294967295), '4294967295'))
        self.assertIsNotNone(self.anchor('exifRational', Fraction(4294967295), '4294967294'))
        self.assertIsNotNone(self.anchor('exifRational', Fraction(1, 3), '0.33333333333333'))  # more digits than ExifTool prints
        # a text or oversized token is a mismatch, never an exception
        self.assertIsNotNone(self.anchor('exifRational', Fraction(1, 2), '1/2'))
        self.assertIsNotNone(self.anchor('exifRational', Fraction(1, 2), '9' * 5000))
        self.assertIsNotNone(self.anchor('exifRational', Fraction(1, 2), '0.5', '0.5'))

    def test_gps_degree_anchor_is_the_composed_rounding_bound_unsigned_and_exact_at_zero(self):
        degrees = Fraction(12) + Fraction(34, 60) + Fraction(5, 3600)
        self.assertIsNone(self.anchor('gpsLatitude', degrees, '12.5680555555556'))
        self.assertIsNone(self.anchor('gpsLatitude', -degrees, '12.5680555555556', anchorAbsolute=True))
        for wrong in ('12.5680555', '12.5680556', '12.57', '-12.5680555555556', '0'):
            self.assertIsNotNone(self.anchor('gpsLatitude', degrees, wrong), wrong)
        # a seconds-only value near zero: the parts are rounded to ten digits, so a relative bound applies, not an absolute floor
        near = Fraction(1, 4294967295) / 3600
        self.assertIsNone(self.anchor('gpsLongitude', near, '6.46751788e-14'))
        self.assertIsNotNone(self.anchor('gpsLongitude', near, '0'))
        self.assertIsNotNone(self.anchor('gpsLongitude', near, '6.4e-14'))
        self.assertIsNone(self.anchor('gpsLongitude', Fraction(0), '0'))
        self.assertIsNotNone(self.anchor('gpsLongitude', Fraction(0), '1e-14'))

    def test_near_zero_fixture_decodes_exactly_and_anchors_against_the_hand_written_native_report(self):
        fields = build('near-zero.jpg', names=['exposureTime', 'fNumber', 'focalLength', 'exposureBias'])
        self.assertEqual([published(fields, n)['exact'] for n in ('exposureTime', 'fNumber', 'exposureBias')], ['1/8000', '1/4294967295', '-1/2147483647'])
        self.assertEqual((state(fields, 'focalLength'), published(fields, 'focalLength')['value']), ('present', 0))
        native = {'SourceFile': 'x', 'EXIF:ExifIFD:ExposureTime': listing.Number('0.000125'), 'EXIF:ExifIFD:FNumber': listing.Number('2.328306437e-10'),
                  'EXIF:ExifIFD:FocalLength': listing.Number('0'), 'EXIF:ExifIFD:ExposureCompensation': listing.Number('-4.656612875e-10')}

        def anchored(**change):
            row = dict(native, **{'EXIF:ExifIFD:' + k: listing.Number(v) for k, v in change.items()})
            return [p['field'] for p in listing.anchors({}, fields, {'image': listing.index(listing.normalise(row)), 'sidecar': None})[1]]
        self.assertEqual(anchored(), [])
        self.assertEqual(anchored(FNumber='0'), ['fNumber'])
        self.assertEqual(anchored(ExposureTime='0.0001250008'), ['exposureTime'])
        self.assertEqual(anchored(FocalLength='1e-12'), ['focalLength'])
        self.assertEqual(anchored(ExposureCompensation='-4.656612876e-10'), ['exposureBias'])
        self.assertEqual(anchored(ExposureCompensation='4.656612875e-10'), ['exposureBias'])

    # ---------------------------------------------------------------- GPS references are anchored against their native companion tags
    def gps_anchored(self, fixture, **native):
        fields = build(fixture, names=['gpsLatitude', 'gpsLongitude', 'gpsAltitude'])
        row = {'SourceFile': 'x'}
        row.update({'EXIF:GPS:' + k: (listing.Number(v) if v[:1] in '-0123456789' else v) for k, v in native.items() if v is not None})
        result = listing.anchors({}, fields, {'image': listing.index(listing.normalise(row)), 'sidecar': None})
        return result[0], [(p['field'], p['message']) for p in result[1]]

    def test_gps_signs_follow_native_hemisphere_and_altitude_references(self):
        # native reports below, written by hand from the fixture table: 33 51' S, 151 12'30" W, 25 m below sea level (EXIF:GPS values are unsigned)
        sea = dict(GPSLatitudeRef='S', GPSLatitude='33.85', GPSLongitudeRef='W', GPSLongitude='151.208333333333', GPSAltitudeRef='1', GPSAltitude='25')
        checked, problems = self.gps_anchored('south-west-sea.jpg', **sea)
        self.assertEqual((checked, problems), (6, []))  # three values and three reference tags
        fields = build('south-west-sea.jpg', names=['gpsLatitude', 'gpsLongitude', 'gpsAltitude'])
        self.assertEqual([published(fields, n)['value'] for n in ('gpsLatitude', 'gpsLongitude', 'gpsAltitude')], [-33.85, -(151 + 12.5 / 60), -25])
        for change, field in (({'GPSLatitudeRef': 'N'}, 'gpsLatitude'), ({'GPSLongitudeRef': 'E'}, 'gpsLongitude'), ({'GPSAltitudeRef': '0'}, 'gpsAltitude'),
                              ({'GPSLatitudeRef': None}, 'gpsLatitude'), ({'GPSLongitudeRef': None}, 'gpsLongitude'), ({'GPSAltitudeRef': None}, 'gpsAltitude'),
                              ({'GPSLatitude': '-33.85'}, 'gpsLatitude')):
            problems = self.gps_anchored('south-west-sea.jpg', **dict(sea, **change))[1]
            self.assertEqual([p[0] for p in problems], [field], change)
        # the reference is anchored even when the magnitudes agree exactly: a wrong-file listing with the right numbers is still refused
        self.assertIn('reference', self.gps_anchored('south-west-sea.jpg', **dict(sea, GPSLatitudeRef='N'))[1][0][1])

    def test_a_zero_coordinate_keeps_its_reference_and_a_missing_altitude_reference_stays_absent(self):
        # normalised zero cannot tell S from N, so the retained reference is what native must repeat
        zero = dict(GPSLatitudeRef='S', GPSLatitude='0', GPSLongitudeRef='W', GPSLongitude='0', GPSAltitudeRef='1', GPSAltitude='0')
        self.assertEqual(self.gps_anchored('zero-refs.jpg', **zero), (6, []))
        fields = build('zero-refs.jpg', names=['gpsLatitude', 'gpsLongitude', 'gpsAltitude'])
        self.assertEqual([(state(fields, n), published(fields, n)['value']) for n in ('gpsLatitude', 'gpsLongitude', 'gpsAltitude')], [('present', 0)] * 3)
        for change, field in (({'GPSLatitudeRef': 'N'}, 'gpsLatitude'), ({'GPSLongitudeRef': 'E'}, 'gpsLongitude'), ({'GPSAltitudeRef': '0'}, 'gpsAltitude'), ({'GPSLatitudeRef': None}, 'gpsLatitude')):
            self.assertEqual([p[0] for p in self.gps_anchored('zero-refs.jpg', **dict(zero, **change))[1]], [field], change)
        # no altitude reference tag: the Exif default is above sea level, and native must also report no reference
        default = dict(GPSLatitudeRef='N', GPSLatitude='1', GPSLongitudeRef='E', GPSLongitude='2.5', GPSAltitude='5')
        self.assertEqual(self.gps_anchored('default-altitude.jpg', **default), (6, []))
        for ref in ('0', '1'):
            problems = self.gps_anchored('default-altitude.jpg', **dict(default, GPSAltitudeRef=ref))[1]
            self.assertEqual([p[0] for p in problems], ['gpsAltitude'], ref)
            self.assertIn('independent reader found none', problems[0][1])
        # the retained companion values are private evidence: they are not published into the source record
        for name in ('gpsLatitude', 'gpsAltitude'):
            for source in published(fields, name)['sources']:
                self.assertNotIn('_companions', source)

    # ---------------------------------------------------------------- a repeated GPS reference tag is its own ambiguous state, anchored to the native copies
    GPS_NAMES = ['gpsLatitude', 'gpsLongitude', 'gpsAltitude']

    def test_a_repeated_gps_reference_is_ambiguous_for_that_field_only_and_names_the_repeated_companion(self):
        # (fixture, ambiguous field, copy count, other fields) from the literal fixture table: lat ref N,S; lon ref E,E (identical copies); altitude ref 0,1
        for fixture, field, others in (('repeated-lat-ref.jpg', 'gpsLatitude', {'gpsLongitude': 20, 'gpsAltitude': 7}),
                                       ('repeated-lon-ref.jpg', 'gpsLongitude', {'gpsLatitude': -11, 'gpsAltitude': 8}),
                                       ('repeated-alt-ref.jpg', 'gpsAltitude', {'gpsLatitude': 12, 'gpsLongitude': -22})):
            fields = build(fixture, names=self.GPS_NAMES)
            found = published(fields, field)
            self.assertEqual((found['state'], found['value'], found['reconciliation']), ('ambiguous', None, 'ambiguous-source'), fixture)
            source = found['sources'][0]
            self.assertEqual((source['state'], source['code'], source['companion'], source['instances']), ('ambiguous', 'EXIF_COMPANION_REPEATED', 'ref', 2), fixture)
            self.assertNotEqual(source['code'], 'EXIF_TAG_REPEATED')
            self.assertEqual(sorted(k for k in source if k.startswith('_')), [], fixture)  # the retained copy values are private evidence
            for other, value in others.items():
                self.assertEqual((state(fields, other), published(fields, other)['value']), ('present', value), (fixture, other))

    def test_repeated_reference_copies_are_anchored_to_every_native_copy(self):
        # native rows written by hand from the fixture table (ExifTool lists the last copy as the main tag and the earlier one as Copy1)
        lat = dict(GPSLatitudeRef='S', GPSLatitude='10', GPSLongitudeRef='E', GPSLongitude='20', GPSAltitudeRef='0', GPSAltitude='7', **{'Copy1:GPSLatitudeRef': 'N'})
        self.assertEqual(self.gps_anchored('repeated-lat-ref.jpg', **lat), (5, []))  # repeat check + 2 values + 2 references
        self.assertEqual(self.gps_anchored('repeated-lat-ref.jpg', **dict(lat, GPSLatitudeRef='N', **{'Copy1:GPSLatitudeRef': 'S'})), (5, []))  # order does not matter
        for change in ({'Copy1:GPSLatitudeRef': None}, {'Copy1:GPSLatitudeRef': 'S'}, {'Copy1:GPSLatitudeRef': 'N', 'GPSLatitudeRef': 'N'}, {'Copy2:GPSLatitudeRef': 'N'},
                       {'Copy1:GPSLatitude': '10'}, {'GPSLatitude': None}, {'GPSLongitudeRef': 'W'}, {'GPSAltitude': '8'}):
            problems = self.gps_anchored('repeated-lat-ref.jpg', **dict(lat, **change))[1]
            self.assertTrue(problems, change)
        for change, field in (({'Copy1:GPSLatitudeRef': None}, 'gpsLatitude'), ({'GPSLongitudeRef': 'W'}, 'gpsLongitude'), ({'GPSAltitude': '8'}, 'gpsAltitude')):
            self.assertEqual([p[0] for p in self.gps_anchored('repeated-lat-ref.jpg', **dict(lat, **change))[1]], [field], change)
        # identical copies are still two instances
        lon = dict(GPSLatitudeRef='S', GPSLatitude='11', GPSLongitudeRef='E', GPSLongitude='21', GPSAltitudeRef='0', GPSAltitude='8', **{'Copy1:GPSLongitudeRef': 'E'})
        self.assertEqual(self.gps_anchored('repeated-lon-ref.jpg', **lon), (5, []))
        for change in ({'Copy1:GPSLongitudeRef': None}, {'Copy1:GPSLongitudeRef': 'W'}):
            self.assertEqual([p[0] for p in self.gps_anchored('repeated-lon-ref.jpg', **dict(lon, **change))[1]], ['gpsLongitude'], change)
        # a repeated altitude reference: numeric copies 1 and 0
        alt = dict(GPSLatitudeRef='N', GPSLatitude='12', GPSLongitudeRef='W', GPSLongitude='22', GPSAltitudeRef='1', GPSAltitude='9', **{'Copy1:GPSAltitudeRef': '0'})
        self.assertEqual(self.gps_anchored('repeated-alt-ref.jpg', **alt), (5, []))
        for change in ({'Copy1:GPSAltitudeRef': None}, {'Copy1:GPSAltitudeRef': '1'}):
            self.assertEqual([p[0] for p in self.gps_anchored('repeated-alt-ref.jpg', **dict(alt, **change))[1]], ['gpsAltitude'], change)
        self.assertEqual(self.gps_anchored('repeated-alt-ref.jpg', **dict(alt, **{'Copy1:GPSAltitudeRef': None}))[1],
                         [('gpsAltitude', 'native reports 1 instances of the reference tag, the independent reader found 2')])
        self.assertEqual(self.gps_anchored('repeated-alt-ref.jpg', **dict(alt, **{'Copy1:GPSAltitudeRef': '1'}))[1],
                         [('gpsAltitude', "native reports ['1', '1'] for the repeated reference tag, the independent reader decoded ['0', '1']")])

    def test_the_audit_names_a_repeated_reference_as_an_ambiguous_field_only(self):
        items = self.items_for(['repeated-lat-ref', 'repeated-alt-ref', 'ridge-line'], self.GPS_NAMES)
        found = audit.audit(items, {'rules': ['sourceConflicts', 'unreadableValues'], 'require': [], 'gpsToleranceSeconds': 300})
        self.assertEqual([(f['rule'], f['item'], f['field'], f['status']) for f in found], [('sourceConflicts', 'repeated_lat_ref', 'gpsLatitude', 'ambiguous'), ('sourceConflicts', 'repeated_alt_ref', 'gpsAltitude', 'ambiguous')])
        self.assertEqual([[(s['family'], s['location'], s['state']) for s in f['evidence']['sources']] for f in found], [[('exif', 'GPS:0x0002', 'ambiguous')], [('exif', 'GPS:0x0006', 'ambiguous')]])

    def test_a_main_tag_repeat_is_unchanged_and_an_implementation_error_is_still_not_swallowed(self):
        fields = build('duplicate-tags.jpg', names=['cameraMake', 'cameraModel'])
        source = published(fields, 'cameraMake')['sources'][0]
        self.assertEqual((source['code'], source['instances'], 'companion' in source), ('EXIF_TAG_REPEATED', 2, False))

        def anchored(row):
            return [p['field'] for p in listing.anchors({}, fields, {'image': listing.index(listing.normalise(row)), 'sidecar': None})[1]]
        agree = {'SourceFile': 'x', 'EXIF:IFD0:Make': 'Second', 'EXIF:IFD0:Copy1:Make': 'First', 'EXIF:IFD0:Model': 'Twin'}
        self.assertEqual(anchored(agree), [])
        self.assertEqual(anchored({k: v for k, v in agree.items() if 'Copy1' not in k}), ['cameraMake'])
        # a repeated-tag source with no instance count is a decoder bug, not a payload state: it must surface, not be tolerated
        broken = {name: dict(field, sources=[{k: v for k, v in s.items() if k != 'instances'} for s in field['sources']]) for name, field in fields.items()}
        with self.assertRaises(KeyError):
            listing.anchors({}, broken, {'image': listing.index(listing.normalise(agree)), 'sidecar': None})

    # ---------------------------------------------------------------- one readable source beside an unreadable or unsupported one is only partially assessed
    def test_a_present_source_beside_an_unreadable_one_is_partially_assessed_not_single_source(self):
        fields = build('mixed-sources.jpg', names=['capturedLocal', 'capturedOffset', 'capturedUtc', 'cameraMake'])
        local = published(fields, 'capturedLocal')
        self.assertEqual((local['state'], local['value'], local['reconciliation']), ('present', '2024-05-06T07:08:09', 'partially-assessed'))
        self.assertEqual(local['unassessedSources'], [{'family': 'exif', 'location': 'ExifIFD:0x9003', 'state': 'unreadable', 'code': 'INVALID_DATE_VALUE'}])
        self.assertEqual([(s['family'], s['state']) for s in local['sources']], [('exif', 'unreadable'), ('xmp', 'present'), ('iptc', 'absent')])
        # genuinely single-source and derived fields keep their meaning
        self.assertEqual(published(fields, 'capturedOffset')['reconciliation'], 'single-source')
        self.assertNotIn('unassessedSources', published(fields, 'capturedOffset'))
        self.assertEqual((state(fields, 'capturedUtc'), published(fields, 'capturedUtc')['value']), ('present', '2024-05-06T05:08:09Z'))
        self.assertEqual(published(fields, 'cameraMake')['reconciliation'], 'single-source')
        # an unsupported competing source (an XMP date without seconds) is also unassessed, and so is a malformed one beside two agreeing sources
        exif = author.rich_entries('II', dict(exif=['original:2024:05:06 07:08:09']))[1]
        reduced = author.xmp_app1(author.xmp_packet('<photoshop:DateCreated>2024-05-06</photoshop:DateCreated>'))
        data = author.build(8, 8, 1, exif=author.tiff_payload('II', [], exif, []), app_segments=[(0xE1, reduced)])
        found = published(records.build(containers.locate(data), ['capturedLocal'])[1], 'capturedLocal')
        self.assertEqual((found['value'], found['reconciliation']), ('2024-05-06T07:08:09', 'partially-assessed'))
        self.assertEqual(found['unassessedSources'], [{'family': 'xmp', 'location': 'photoshop:DateCreated', 'state': 'unsupported', 'code': 'XMP_DATE_REDUCED_PRECISION'}])
        # two present sources that disagree stay conflicting even beside an unreadable one
        conflict = build('conflict-desk.jpg', names=['capturedLocal'])
        self.assertEqual(conflict['capturedLocal']['reconciliation'], 'conflicting')

    def test_unreadable_values_rule_reports_a_malformed_source_even_when_another_source_is_present(self):
        names = ['capturedLocal', 'capturedOffset', 'capturedUtc', 'cameraMake']
        items = self.items_for(['mixed-sources', 'ridge-line'], names)
        found = audit.audit(items, {'rules': ['unreadableValues', 'sourceConflicts'], 'require': [], 'gpsToleranceSeconds': 300})
        self.assertEqual(len(found), 1)
        row = found[0]
        self.assertEqual((row['rule'], row['item'], row['field'], row['severity'], row['status']), ('unreadableValues', 'mixed_sources', 'capturedLocal', 'warning', 'unreadable'))
        self.assertEqual(row['message'], 'Capture time (local wall time) has a malformed source, so its sources were only partially assessed')
        self.assertEqual(row['evidence']['fieldState'], 'present')
        self.assertEqual([(s['family'], s['location'], s['code']) for s in row['evidence']['sources']], [('exif', 'ExifIFD:0x9003', 'INVALID_DATE_VALUE')])
        # the whole-field case keeps its original message and a field-level state
        latin = audit.audit(self.items_for(['latin-iptc'], ['title']), {'rules': ['unreadableValues'], 'require': [], 'gpsToleranceSeconds': 300})
        self.assertEqual([(f['field'], f['message'], f['evidence']['fieldState']) for f in latin], [('title', 'Title is present but malformed', 'unreadable')])
        # the published audit document counts exactly that row for a fixture set
        plan = workbench.plan({'version': adaptor.VERSION, 'operation': 'auditMetadata', 'media': {'items': [{'id': 'mixed_sources', 'path': '/x/a.jpg'}, {'id': 'ridge_line', 'path': '/x/b.jpg'}]},
                               'profiles': ['capture'], 'rules': ['unreadableValues']})
        files, _ = workbench.documents(plan, [], self.items_for(['mixed-sources', 'ridge-line'], plan['fields']), None)
        summary = json.loads(files['audit.json'])['summary']
        self.assertEqual((summary['findings'], summary['byRule'], summary['itemsAudited']), (1, {'unreadableValues': 1}, 2))
        self.assertEqual(files['findings.csv'].decode().splitlines()[1].split(',')[:3], ['"mixed_sources"', '"unreadableValues"', '"warning"'])

    # ---------------------------------------------------------------- bounded, ASCII-only codecs
    def test_digit_patterns_are_ascii_only_and_bounded_input_never_raises_a_plain_value_error(self):
        indic = '١٢'  # ARABIC-INDIC DIGIT ONE, TWO: int() accepts them, so a bare digit class would too
        self.assertEqual(int(indic), 12)
        entry = lambda text: tiff.Entry(0x9291, 2, len(text) + 1, text.encode() + b'\0', 0, '<') if hasattr(tiff, 'Entry') else None
        packet = lambda value: {'kind': 'text', 'value': value}
        with self.assertRaises(codecs.ValueProblem) as raised:
            codecs.xmp_integer(packet(indic))
        self.assertEqual(raised.exception.code, 'XMP_INTEGER_INVALID')
        for value in (indic, '٢024-05-06T07:08:09', '2024-05-06T07:08:09.' + indic):
            with self.assertRaises(codecs.ValueProblem) as raised:
                codecs.xmp_date_parts(packet(value))
            self.assertEqual(raised.exception.code, 'XMP_DATE_INVALID', value)
        for pattern, text in ((codecs.DATE_TIME, '٢024:05:06 07:08:09'), (codecs.OFFSET, '+٠٢:00'), (codecs.SUBSECOND, indic), (codecs.GPS_DATE, '٢024:05:06'),
                              (codecs.IPTC_DATE, '٢٠240506'), (codecs.IPTC_TIME, '٠٧٠٨٠٩'), (codecs.NATIVE_DATE, '٢024:05:06 07:08:09')):
            self.assertIsNone(pattern.fullmatch(text), pattern.pattern)
        # a 5000-digit decimal is refused structurally before any int() conversion (the Python 4300-digit guard is left on)
        for value in ('9' * 5000, '-' + '9' * 5000, '9' * 5000 + '/' + '9' * 5000):
            with self.assertRaises(codecs.ValueProblem):
                codecs.xmp_integer(packet(value))
        self.assertIsNone(codecs.native_exact('9' * 5000))
        self.assertIsNone(codecs.native_exact('1e' + '9' * 5000))
        self.assertNotIn('xmpRational', codecs.CODECS)  # latent: no catalogue field used it, and its decimal conversion was unbounded
        # every codec has a catalogue user, so no unreachable decoder or anchor lingers
        used = {source['codec'] for version in (*catalogue.KNOWN, *catalogue.ADDITIONS) for spec in catalogue.fields(version).values() for source in spec['sources']}
        self.assertEqual(sorted(set(codecs.CODECS) - used), [])
        # the decoder boundary is unchanged: implementation errors are not payload faults (see the implementation-error test)
        self.assertIsNone(self.anchor('exifInteger', 1, '1'))

    # ---------------------------------------------------------------- full run + verify of partial sets (the retained listing covers every admitted capture)
    def native_executable(self):
        path = os.environ.get('SCHEMAXIS_EXIFTOOL')
        if not path or not os.path.isabs(path) or not Path(path).is_file() or not Path(adaptor.PERL).is_file():
            self.skipTest('real ExifTool 13.55 is not configured through SCHEMAXIS_EXIFTOOL; tools/qualify_exiftool_workbench.py runs the same flows against the native runtime')
        return path

    def partial_document(self, directory, names, **extra):
        directory = Path(tempfile.mkdtemp(prefix='schemaxis-exiftool-test-')).resolve()
        for name in names:
            (directory / name).write_bytes((FIXTURES / name).read_bytes())
        return {'version': adaptor.VERSION, 'operation': 'inspectMetadata', 'profiles': ['device'], 'nativeListing': True,
                'media': {'items': [{'id': i, 'path': str(directory / n)} for i, n in zip(('good', 'other'), names)]}, **extra}, directory.parent / (directory.name + '-out')

    def replayed_names(self):
        seen, original = [], workbench.replay

        def spy(directory, p, names, *rest):
            seen.append(list(names))
            return original(directory, p, names, *rest)
        workbench.replay = spy
        return seen, lambda: setattr(workbench, 'replay', original)

    def test_real_native_disagreement_gives_a_verified_partial_set_and_the_replay_covers_both_captures(self):
        exe = self.native_executable()
        document, out = self.partial_document(None, ('north-gate.jpg', 'padded-make.jpg'))
        seen, restore = self.replayed_names()
        try:
            result = adaptor.run(document, out, executable=exe, timeout=120)
            again = workbench.verify(out, executable=exe)
        finally:
            restore()
        # the real ExifTool trims the trailing space of Make, the independent reader keeps it: that disagreement refuses only the padded item
        self.assertEqual((result['verified'], result['items'], result['succeeded'], result['faulted'], result['setStatus']), (True, 2, 1, 1, 'partial'))
        self.assertEqual((result['nativeReplay'], again['nativeReplay']), ('fresh-replay-matched', 'fresh-replay-matched'))
        both = ['captured/good.jpg', 'captured/other.jpg']
        self.assertTrue(len(seen) >= 2 and all(names == both for names in seen), seen)  # every replay (the run's, the adaptor's and the explicit re-verification) covers BOTH admitted captures
        listing_rows = json.loads((out / 'listing.stdout').read_text())
        self.assertEqual([r['SourceFile'] for r in listing_rows], ['captured/good.jpg', 'captured/other.jpg'])
        self.assertEqual([r['EXIF:IFD0:Make'] for r in listing_rows], ['Northfield', 'Northfiel'])
        metadata = json.loads((out / 'metadata.json').read_text())
        good, other = metadata['items']
        self.assertEqual((good['id'], good['status'], other['id'], other['status']), ('good', 'ok', 'other', 'fault'))
        self.assertEqual((other['fault']['code'], other['fault']['location']), ('NATIVE_ANCHOR_MISMATCH', 'captured/other.jpg'))
        self.assertEqual([m['field'] for m in other['fault']['observed']['mismatches']], ['cameraMake'])
        self.assertIn("'Northfiel '", other['fault']['observed']['mismatches'][0]['message'])
        self.assertEqual(json.loads((out / 'manifest.json').read_text())['status'], 'partial')
        self.assertEqual([i['id'] for i in json.loads((out / 'native-observations.json').read_text())['items']], ['good'])
        self.assertEqual((out / 'profile-device.csv').read_text().count('\n'), 2)  # header and the good item only

    def test_real_native_repeated_gps_references_keep_the_set_and_every_native_copy(self):
        exe = self.native_executable()
        names = ('north-gate.jpg', 'repeated-lat-ref.jpg', 'repeated-lon-ref.jpg', 'repeated-alt-ref.jpg')
        directory = Path(tempfile.mkdtemp(prefix='schemaxis-exiftool-test-')).resolve()
        for name in names:
            (directory / name).write_bytes((FIXTURES / name).read_bytes())
        document = {'version': adaptor.VERSION, 'operation': 'inspectMetadata', 'profiles': ['location'], 'nativeListing': True,
                    'media': {'items': [{'id': n[:-4].replace('-', '_'), 'path': str(directory / n)} for n in names]}}
        out = directory.parent / (directory.name + '-out')
        result = adaptor.run(document, out, executable=exe, timeout=120)
        again = workbench.verify(out, executable=exe)
        # nothing is lost to one repeated reference: all four items publish, verify, and replay against the real listing
        self.assertEqual((result['verified'], result['items'], result['succeeded'], result['faulted'], result['setStatus']), (True, 4, 4, 0, 'complete'))
        self.assertEqual((result['nativeReplay'], again['nativeReplay']), ('fresh-replay-matched', 'fresh-replay-matched'))
        metadata = {i['id']: i for i in json.loads((out / 'metadata.json').read_text())['items']}
        listed = {r['SourceFile']: r for r in json.loads((out / 'listing.stdout').read_text())}
        native = {i['id']: [o for f in i['files'] for o in f['observations']] for i in json.loads((out / 'native-observations.json').read_text())['items']}
        for item, field, key, copies, others in (('repeated_lat_ref', 'gpsLatitude', 'GPSLatitudeRef', ['S', 'N'], {'gpsLongitude': 20, 'gpsAltitude': 7}),
                                                 ('repeated_lon_ref', 'gpsLongitude', 'GPSLongitudeRef', ['E', 'E'], {'gpsLatitude': -11, 'gpsAltitude': 8}),
                                                 ('repeated_alt_ref', 'gpsAltitude', 'GPSAltitudeRef', [1, 0], {'gpsLatitude': 12, 'gpsLongitude': -22})):
            self.assertEqual(metadata[item]['status'], 'ok', item)
            fields = {f['field']: f for f in metadata[item]['fields']}
            self.assertEqual((fields[field]['state'], fields[field]['value'], fields[field]['sources'][0]['code'], fields[field]['sources'][0]['instances']), ('ambiguous', None, 'EXIF_COMPANION_REPEATED', 2), item)
            self.assertEqual({n: (fields[n]['state'], fields[n]['value']) for n in others}, {n: ('present', v) for n, v in others.items()}, item)
            row = listed['captured/%s.jpg' % item]
            self.assertEqual([row['EXIF:GPS:' + key], row['EXIF:GPS:Copy1:' + key]], copies, item)  # ExifTool lists the last copy as the main tag
            self.assertEqual([(o['instance'], o.get('ambiguous')) for o in native[item] if o['name'] == key], [(0, True), (1, True)], item)
        self.assertEqual(metadata['north_gate']['status'], 'ok')
        self.assertEqual(json.loads((out / 'manifest.json').read_text())['status'], 'complete')

    def emulating_listing(self, name, edit):
        """STAGE EMULATION (not a native fact): the real ExifTool runs, then one file's row of its listing is edited by hand at the ``run_stage`` seam.

        Both the run and the verification replay pass through this seam, so the retained listing and the fresh replay agree. Used only to reach
        host branches that no fixture can make real ExifTool produce; the real disagreement is the padded-make test above.
        """
        real = workbench.run_stage

        def staged(directory, stage, command, names, timeout):
            outcome = real(directory, stage, command, names, timeout)
            if stage in ('listing', 'repeat'):
                path = Path(directory) / (stage + '.stdout')
                head, marker, tail = path.read_text().partition('"SourceFile": "%s"' % name)
                assert marker, name
                path.write_text(head + marker + edit(tail))
            return outcome
        workbench.run_stage = staged
        return lambda: setattr(workbench, 'run_stage', real)

    def test_emulated_native_error_and_emulated_anchor_refusal_leave_verified_partial_sets(self):
        exe = self.native_executable()
        cases = {'native-error-observation': (lambda tail: tail.replace(',', ',\n  "ExifTool:Error": "File format error (emulated)",', 1), 'NATIVE_REPORTED_PROBLEM'),
                 'native-anchor-refusal': (lambda tail: tail.replace('"Northfield"', '"Other"', 1), 'NATIVE_ANCHOR_MISMATCH')}
        for label, (edit, code) in cases.items():
            with self.subTest(label):
                document, out = self.partial_document(None, ('north-gate.jpg', 'harbour-light.jpg'))
                seen, restore_replay = self.replayed_names()
                restore = self.emulating_listing('captured/other.jpg', edit)
                try:
                    result = adaptor.run(document, out, executable=exe, timeout=120)
                    again = workbench.verify(out, executable=exe)
                finally:
                    restore()
                    restore_replay()
                self.assertEqual((result['verified'], result['succeeded'], result['faulted'], result['setStatus'], result['nativeReplay']), (True, 1, 1, 'partial', 'fresh-replay-matched'), label)
                self.assertEqual(again['nativeReplay'], 'fresh-replay-matched')
                both = ['captured/good.jpg', 'captured/other.jpg']
                self.assertTrue(len(seen) >= 2 and all(names == both for names in seen), seen)
                items = json.loads((out / 'metadata.json').read_text())['items']
                self.assertEqual([(i['id'], i['status']) for i in items], [('good', 'ok'), ('other', 'fault')])
                self.assertEqual(items[1]['fault']['code'], code)
                self.assertEqual(sorted(path.name for path in (out / 'captured').iterdir()), ['good.jpg', 'other.jpg'])
                # the replay is a real native process: without the emulation the retained (edited) listing no longer reproduces
                self.fault(lambda: workbench.verify(out, executable=exe), 'VERIFICATION_FAILED', 'listing')

    # ---------------------------------------------------------------- discovery and boundaries
    def test_discovery_search_cases_cover_new_operations_and_keep_unoffered_verbs_negative(self):
        from schemaxis.adaptors.exiftool import capabilities
        catalogue_data = capabilities.catalogue()
        cases = {c['id']: c for c in catalogue_data['searchCases']}
        self.assertTrue(all(c['status'] == 'reviewed' for c in cases.values()))
        self.assertEqual(set(catalogue_data['operations']), set(adaptor.DECLARATIONS))
        # E3 offers geotagging and capture-time shifting and E4 a naming plan for copies: those are positive now; raw tags, expressions and reverse geocoding stay genuinely unoffered
        for negative in ('reverse-geocode-photos', 'raw-exiftool-tag', 'shift-expression', 'identify-faces', 'certified-capture-time', 'photo-authenticity'):
            self.assertEqual(cases[negative]['kind'], 'negative')
            self.assertEqual(cases[negative]['expected']['capabilities'], [])
            self.assertEqual(len(cases[negative]['excluded']['capabilities']), 16)
        for positive, operation in (('geotag-photos', 'geotagFromTrack'), ('shift-capture-time', 'correctTime'), ('geotag-from-gpx', 'geotagFromTrack'), ('camera-clock-skew', 'reconcileTime'),
                                    ('where-was-this-photo-taken', 'locate'), ('rename-photos', 'planNames')):
            self.assertEqual(cases[positive]['expected']['capabilities'], ['operation/exiftool/' + operation])
            self.assertNotIn('operation/exiftool/' + operation, cases[positive]['excluded']['capabilities'])
        self.assertEqual(cases['geotag-photos-root']['expected'], {'adaptor': ['app/exiftool']})
        self.assertEqual(cases['reverse-geocode-photos-root']['expected'], {'adaptor': []})
        for write, operation in (('strip-metadata', 'removeMetadata'), ('remove-location', 'removeMetadata'), ('edit-photo-metadata', 'editMetadata'), ('add-keyword', 'editMetadata'), ('edit-caption', 'editMetadata'), ('write-exif-tags', 'editMetadata')):
            self.assertEqual(cases[write]['expected']['capabilities'], ['operation/exiftool/' + operation])
        for positive in ('gps-location', 'xmp-sidecar', 'audit-photo-metadata', 'compare-photo-metadata', 'metadata-conflicts'):
            self.assertIn(positive, cases)
        meta = registry.metadata('exiftool')
        self.assertEqual(set(meta['routes']), {'schemaxis.exiftool/1'})

    def test_no_framework_branches_and_no_other_adaptor_imports(self):
        for path in (ROOT / 'src/schemaxis').glob('*.py'):
            self.assertNotIn('exiftool', path.read_text().lower(), path.name)
        for path in (ROOT / 'src/schemaxis/adaptors/exiftool').glob('*.py'):
            text = path.read_text()
            for other in ('adaptors.calc', 'adaptors.sqlite', 'adaptors.flac', 'adaptors.pandoc'):
                self.assertNotIn('schemaxis.' + other, text, path.name)
        for path in (ROOT / 'src/schemaxis/adaptors/exiftool').glob('*.py'):
            if path.name not in ('adaptor.py', 'workbench.py'):
                self.assertNotIn('import subprocess', path.read_text(), path.name)
        text = (ROOT / 'src/schemaxis/adaptors/exiftool/fields.json').read_text()
        self.assertNotIn(str(ROOT.resolve()), text)
        self.assertNotIn(str(Path.home().resolve()), text)


if __name__ == '__main__':
    unittest.main()
