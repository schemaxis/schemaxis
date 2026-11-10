"""Host-only ExifTool contract checks: planning, discovery, independent JPEG/EXIF admission and strict native-JSON comparison. No native process runs."""
import copy
import datetime
import json
from pathlib import Path
import sys
import unittest

from schemaxis.adaptors import registry
from schemaxis.adaptors.exiftool import adaptor, jpeg
from schemaxis.core.faults import SchemaxisError

ROOT = Path(__file__).resolve().parents[2]
EXAMPLES = ROOT / 'examples/schemaxis'
FIXTURES = EXAMPLES / 'fixtures/exiftool'
sys.path.insert(0, str(ROOT / 'tools'))
import author_exiftool_fixtures as author  # noqa: E402


def example(name): return json.loads((EXAMPLES / name).read_text())


class ExifTool(unittest.TestCase):
    def fault(self, action, code, location=None, **observed):
        with self.assertRaises(SchemaxisError) as raised: action()
        fault = raised.exception.fault
        self.assertEqual(fault.code, code, fault.to_dict())
        if location: self.assertEqual(fault.location, location)
        for key, value in observed.items(): self.assertEqual(fault.observed.get(key), value, fault.to_dict())
        return fault

    def parse(self, data, name='p'): return jpeg.parse(data, '$.photos[0].path', name)

    def test_registered_without_framework_branches(self):
        self.assertIn('exiftool', [p['id'] for p in registry.discover()['providers']])
        for path in (ROOT / 'src/schemaxis').glob('*.py'):
            self.assertNotIn('exiftool', path.read_text().lower(), path.name)

    def test_committed_fixtures_regenerate_exactly_and_match_literal_specifications(self):
        for seed, (name, spec) in enumerate(author.FIXTURES.items(), 1):
            spec = dict(spec)
            data = author.build(spec.pop('width'), spec.pop('height'), seed, **spec)
            self.assertEqual((FIXTURES / (name + '.jpg')).read_bytes(), data, name)
            facts = self.parse(data, name)
            literal = author.FIXTURES[name]
            self.assertEqual((facts['width'], facts['height']), (literal['width'], literal['height']))
            for key, field in (('make', 'make'), ('model', 'model'), ('orientation', 'orientation'), ('original', 'original'), ('offset', 'offset')):
                self.assertEqual(facts[key], literal.get(field), (name, key))

    def test_plan_is_deterministic_immutable_with_stable_order(self):
        document = example('exiftool-baseline.json');original = copy.deepcopy(document)
        first = adaptor.plan(document)
        self.assertEqual(first, adaptor.plan(document));self.assertEqual(document, original)
        self.assertEqual([p['id'] for p in first['photos']], ['north_gate', 'river_bend', 'quarry', 'unmarked'])
        self.assertNotEqual(first, adaptor.plan(example('exiftool-variant.json')))
        command = adaptor.commands('/x/exiftool', first)['extract']
        self.assertEqual(command[:5], [adaptor.PERL, '/x/exiftool', '-config', '', '-json'])
        self.assertEqual(command[-4:], ['captured/north_gate.jpg', 'captured/river_bend.jpg', 'captured/quarry.jpg', 'captured/unmarked.jpg'])
        self.assertEqual(adaptor.commands('/x/exiftool', first)['repeat'], command)

    def test_closed_input_and_exact_faults(self):
        base = example('exiftool-baseline.json')
        self.fault(lambda: adaptor.plan({**base, 'extra': 1}), 'UNKNOWN_ARGUMENT')
        self.fault(lambda: adaptor.plan({**base, 'operation': 'x'}), 'UNKNOWN_OPERATION', '$.operation')
        self.fault(lambda: adaptor.plan(example('exiftool-id-invalid.json')), 'INVALID_PHOTO_ID', '$.photos[0].id')
        self.fault(lambda: adaptor.plan(example('exiftool-duplicate-id-invalid.json')), 'DUPLICATE_PHOTO_ID', '$.photos[1].id', value='site')
        self.fault(lambda: adaptor.plan(example('exiftool-path-relative-invalid.json')), 'INVALID_PHOTO_SOURCE', '$.photos[0].path')
        self.fault(lambda: adaptor.plan(example('exiftool-hash-invalid.json')), 'INVALID_SHA256', '$.photos[0].sha256')
        self.fault(lambda: adaptor.plan({**base, 'photos': []}), 'INVALID_ARGUMENT')
        many = [{'id': f'p{i}', 'path': f'/x/{i}.jpg'} for i in range(17)]
        self.fault(lambda: adaptor.plan({**base, 'photos': many}), 'INVALID_ARGUMENT')
        adaptor.plan({**base, 'photos': many[:16]})
        self.fault(lambda: adaptor.plan({**base, 'photos': [{'id': 'a', 'path': '/x/../y.jpg'}]}), 'INVALID_PHOTO_SOURCE', '$.photos[0].path')
        self.fault(lambda: adaptor.plan({**base, 'photos': [{'id': 'a', 'path': '/x/y.png'}]}), 'INVALID_PHOTO_SOURCE', '$.photos[0].path')

    def test_discovery_search_cases_are_reviewed_and_scoped(self):
        from schemaxis.adaptors.exiftool import capabilities
        catalogue = capabilities.catalogue()
        self.assertTrue(catalogue['searchCases'])
        self.assertTrue(all(c['status'] == 'reviewed' for c in catalogue['searchCases']))
        self.assertIn('inventoryPhotos', catalogue['operations'])

    def test_missing_tags_are_separate_nulls_and_nothing_is_inferred(self):
        facts = self.parse(author.build(8, 8, 1, order='MM'))
        self.assertEqual({k: facts[k] for k in ('make', 'model', 'orientation', 'original', 'offset')}, dict.fromkeys(('make', 'model', 'orientation', 'original', 'offset')))
        only_time = self.parse(author.build(8, 8, 1, original='2024:05:06 07:08:09'))
        self.assertEqual((only_time['original'], only_time['offset'], only_time['make']), ('2024:05:06 07:08:09', None, None))
        only_offset = self.parse(author.build(8, 8, 1, offset='+01:00'))
        self.assertEqual((only_offset['original'], only_offset['offset']), (None, '+01:00'))
        rows = adaptor.rows_for([{'id': 'a'}], [{**only_time}])
        self.assertEqual(rows[0][6:], ['2024-05-06T07:08:09', None, None])
        rows = adaptor.rows_for([{'id': 'a'}], [{**only_offset}])
        self.assertEqual(rows[0][6:], [None, '+01:00', None])

    def test_reader_refuses_with_exact_fault_and_field(self):
        g = author
        cases = [
            ('duplicate make', g.build(8, 8, extra0=[g.ascii_entry(g.IFD0_MAKE, 'B')], make='A'), 'DUPLICATE_EXIF_TAG', 'IFD0:Make'),
            ('duplicate date', g.build(8, 8, original='2024:01:01 00:00:00', extra_exif=[g.ascii_entry(g.EXIF_ORIGINAL, '2025:01:01 00:00:00')]), 'DUPLICATE_EXIF_TAG', 'ExifIFD:DateTimeOriginal'),
            ('bad calendar', g.build(8, 8, original='2023:02:29 10:00:00'), 'INVALID_EXIF_VALUE', 'ExifIFD:DateTimeOriginal'),
            ('bad month', g.build(8, 8, original='2024:13:01 10:00:00'), 'INVALID_EXIF_VALUE', 'ExifIFD:DateTimeOriginal'),
            ('bad hour', g.build(8, 8, original='2024:01:01 24:00:00'), 'INVALID_EXIF_VALUE', 'ExifIFD:DateTimeOriginal'),
            ('dashed date', g.build(8, 8, original='2024-01-01 10:00:00'), 'INVALID_EXIF_VALUE', 'ExifIFD:DateTimeOriginal'),
            ('bad offset', g.build(8, 8, offset='+25:00'), 'INVALID_EXIF_VALUE', 'ExifIFD:OffsetTimeOriginal'),
            ('offset minutes', g.build(8, 8, offset='+01:61'), 'INVALID_EXIF_VALUE', 'ExifIFD:OffsetTimeOriginal'),
            ('orientation zero', g.build(8, 8, orientation=0), 'INVALID_EXIF_VALUE', 'IFD0:Orientation'),
            ('orientation nine', g.build(8, 8, orientation=9), 'INVALID_EXIF_VALUE', 'IFD0:Orientation'),
            ('orientation long', g.build(8, 8, extra0=[g.entry(g.IFD0_ORIENTATION, g.LONG, (3).to_bytes(4, 'little'))]), 'INVALID_EXIF_VALUE', 'IFD0:Orientation'),
            ('make padded', g.build(8, 8, make='Abc '), 'INVALID_EXIF_VALUE', 'IFD0:Make'),
            ('model non-ascii', g.build(8, 8, exif=g.exif_segment(model='Camé')) if False else None, None, None),
            ('make type short', g.build(8, 8, extra0=[g.entry(g.IFD0_MAKE, g.SHORT, b'\x01\x00')]), 'INVALID_EXIF_VALUE', 'IFD0:Make'),
            ('two exif segments', g.build(8, 8, make='A', app1_count=2), 'AMBIGUOUS_EXIF', None),
            ('ifd0 cycle', g.build(8, 8, make='A', ifd0_next=8), 'INVALID_EXIF_STRUCTURE', None),
            ('exif pointer to ifd0', g.build(8, 8, original='2024:01:01 00:00:00', exif_pointer=8), 'INVALID_EXIF_STRUCTURE', 'ExifIFD'),
            ('exif pointer overflow', g.build(8, 8, original='2024:01:01 00:00:00', exif_pointer=10 ** 6), 'INVALID_EXIF_STRUCTURE', 'ExifIFD'),
            ('exif pointer type', g.build(8, 8, original='2024:01:01 00:00:00', exif_pointer_kind=g.SHORT), 'INVALID_EXIF_STRUCTURE', 'IFD0:ExifOffset'),
            ('progressive', g.build(8, 8, sof_marker=0xC2), 'UNSUPPORTED_JPEG', None),
            ('12-bit', g.build(8, 8, precision=12), 'UNSUPPORTED_JPEG', None),
            ('one component', g.build(8, 8, components=1), 'UNSUPPORTED_JPEG', None),
            ('trailing data', g.build(8, 8, trailing=b'\xff\xd8\xff\xd9'), 'UNSUPPORTED_JPEG', None),
            ('truncated', g.build(8, 8, make='A')[:60], 'INVALID_PHOTO_DATA', None),
            ('not jpeg', b'\x89PNG\r\n', 'INVALID_PHOTO_DATA', None),
            ('zero width', g.build(0, 8), 'INVALID_PHOTO_DATA', None),
        ]
        for label, data, code, field in cases:
            if data is None: continue
            fault = self.fault(lambda: self.parse(data, 'site'), code, '$.photos[0].path', photo='site')
            if field: self.assertEqual(fault.observed.get('field'), field, (label, fault.to_dict()))

    def test_string_edges(self):
        self.parse(author.build(8, 8, make='A' * 64))
        self.fault(lambda: self.parse(author.build(8, 8, make='A' * 65)), 'INVALID_EXIF_VALUE', field='IFD0:Make')
        self.fault(lambda: self.parse(author.build(8, 8, make='\x07x')), 'INVALID_EXIF_VALUE', field='IFD0:Make')
        self.assertEqual(self.parse(author.build(8, 8, make='\\N'))['make'], '\\N')
        self.fault(lambda: adaptor.admit_photo(author.build(8, 8, make='\\N'), 0, {'id': 'a', 'path': '/x.jpg'}), 'INVALID_EXIF_VALUE', '$.photos[0].path', field='IFD0:Make')
        self.assertEqual(self.parse(author.build(8, 8, model='=cmd|x!A1'))['model'], '=cmd|x!A1')
        self.fault(lambda: self.parse(b'\xff\xd8' + b'\0' * (jpeg.MAX_BYTES)), 'PHOTO_RESOURCE_LIMIT')

    def test_utc_arithmetic_matches_datetime_across_boundaries(self):
        for local, offset in (('2024:12:31 23:30:00', '-05:30'), ('2024:01:01 00:10:00', '+02:00'), ('2024:03:01 00:00:00', '+00:01'), ('2023:03:01 00:00:00', '+14:00'),
                              ('2100:12:31 23:59:59', '-12:00'), ('1900:01:01 00:00:00', '+05:45'), ('2024:02:29 12:00:00', '+00:00')):
            minutes = jpeg.check_offset(offset, '$', 'x')
            year, month, day, hour, minute, second = map(int, local.replace(':', ' ').split())
            expected = (datetime.datetime(year, month, day, hour, minute, second) - datetime.timedelta(minutes=minutes))
            if expected.year < 1: continue
            self.assertEqual(jpeg.utc_text(local, minutes), expected.strftime('%Y-%m-%dT%H:%M:%SZ'), (local, offset))

    def test_csv_is_canonical_literal_and_null_token_distinct(self):
        facts = [self.parse((FIXTURES / n).read_bytes()) for n in ('quarry.jpg', 'unmarked.jpg')]
        photos = [{'id': 'quarry'}, {'id': 'unmarked'}]
        csv = adaptor.csv_bytes(adaptor.rows_for(photos, facts)).decode()
        self.assertEqual(csv, '"id","width","height","orientation","cameraMake","cameraModel","capturedLocal","utcOffset","capturedUtc"\n'
                              '"quarry",24,8,3,"Q","=SUM(1+1)","2024-02-29T00:00:00",\\N,\\N\n"unmarked",8,8,\\N,\\N,\\N,\\N,\\N,\\N\n')

    def native(self, p, facts, rows):
        return adaptor.compare_native(json.dumps(rows).encode(), p, facts)

    def test_native_json_comparison_is_strict(self):
        p = adaptor.plan(example('exiftool-variant.json'))
        facts = [self.parse((FIXTURES / n).read_bytes()) for n in ('north-gate.jpg', 'unmarked.jpg')]
        good = [{'SourceFile': 'captured/north_gate.jpg', 'IFD0:Make': 'Northfield', 'IFD0:Model': 'NF-100', 'IFD0:Orientation': 1, 'ExifIFD:DateTimeOriginal': '2024:05:06 07:08:09',
                 'ExifIFD:OffsetTimeOriginal': '+02:00', 'File:ImageWidth': 16, 'File:ImageHeight': 8, 'File:EncodingProcess': 0, 'File:BitsPerSample': 8, 'File:ColorComponents': 3},
                {'SourceFile': 'captured/unmarked.jpg', 'File:ImageWidth': 8, 'File:ImageHeight': 8, 'File:EncodingProcess': 0, 'File:BitsPerSample': 8, 'File:ColorComponents': 3}]
        self.assertEqual(len(self.native(p, facts, good)), 2)
        def mutate(index, **changes):
            rows = copy.deepcopy(good);rows[index].update(changes)
            for key in [k for k, v in changes.items() if v is KeyError]: del rows[index][key]
            return rows
        for label, rows, location in (
                ('width lies', mutate(0, **{'File:ImageWidth': 17}), '$.photos[0].File:ImageWidth'),
                ('orientation as string', mutate(0, **{'IFD0:Orientation': '1'}), '$.photos[0].IFD0:Orientation'),
                ('orientation changed', mutate(0, **{'IFD0:Orientation': 6}), '$.photos[0].IFD0:Orientation'),
                ('make changed', mutate(0, **{'IFD0:Make': 'Other'}), '$.photos[0].IFD0:Make'),
                ('date changed', mutate(0, **{'ExifIFD:DateTimeOriginal': '2024:05:06 07:08:10'}), '$.photos[0].ExifIFD:DateTimeOriginal'),
                ('make dropped', mutate(0, **{'IFD0:Make': KeyError}), '$.photos[0]'),
                ('invented tag', mutate(1, **{'IFD0:Make': 'Invented'}), '$.photos[1]'),
                ('duplicate copy key', mutate(0, **{'IFD0:Copy1:Make': 'Earlier'}), '$.photos[0]'),
                ('warning', mutate(0, **{'ExifTool:Warning': 'Bad'}), '$.photos[0]'),
                ('swapped order', [good[1], good[0]], '$.photos[0]'),
                ('extra record', good + [good[0]], 'extract'),
                ('null swap', mutate(0, **{'IFD0:Model': None}), '$.photos[0].IFD0:Model')):
            code = 'NATIVE_REPORTED_PROBLEM' if label == 'warning' else 'NATIVE_OBSERVATION_MISMATCH'
            self.fault(lambda: self.native(p, facts, rows), code, location)
        self.fault(lambda: adaptor.compare_native(b'[{"SourceFile":"a","SourceFile":"b"}]', p, facts), 'NATIVE_OBSERVATION_MISMATCH', 'extract.stdout')

    def test_minus_zero_offset_is_unknown_and_refused_but_plus_zero_is_accepted(self):
        fault = self.fault(lambda: self.parse(author.build(8, 8, original='2024:01:01 00:00:00', offset='-00:00'), 'site'), 'INVALID_EXIF_VALUE', '$.photos[0].path', photo='site', field='ExifIFD:OffsetTimeOriginal', value='-00:00')
        self.assertIn('unknown offset', fault.message)
        zero = self.parse(author.build(8, 8, original='2024:01:01 00:00:00', offset='+00:00'))
        self.assertEqual((zero['offset'], zero['original']), ('+00:00', '2024:01:01 00:00:00'))
        edge = self.parse(author.build(8, 8, original='2000:02:29 12:00:00', offset='+14:00'))
        self.assertEqual(edge['offset'], '+14:00')
        self.parse(author.build(8, 8, original='2024:01:01 00:00:00', offset='-12:00'))
        for label, original, offset in (('april 31', '2024:04:31 00:00:00', None), ('minute 60', '2024:01:01 00:60:00', None), ('second 60', '2024:01:01 00:00:60', None),
                                        ('1900 is not leap', '1900:02:29 00:00:00', None), ('year 2101', '2101:01:01 00:00:00', None),
                                        ('-12:30', '2024:01:01 00:00:00', '-12:30'), ('+14:30', '2024:01:01 00:00:00', '+14:30'), ('+05:60', '2024:01:01 00:00:00', '+05:60'),
                                        ('Z', '2024:01:01 00:00:00', 'Z'), ('no colon', '2024:01:01 00:00:00', '+0200')):
            data = author.build(8, 8, original=original, **({'offset': offset} if offset else {}))
            self.fault(lambda: self.parse(data), 'INVALID_EXIF_VALUE', '$.photos[0].path', field='ExifIFD:OffsetTimeOriginal' if offset else 'ExifIFD:DateTimeOriginal')

    def test_duplicate_source_files_are_refused_before_any_content_is_read(self):
        import os
        import tempfile
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            a = root / 'a.jpg';a.write_bytes(author.build(8, 8, make='A'))
            copy = root / 'copy.jpg';copy.write_bytes(a.read_bytes())
            hard = root / 'hard.jpg';os.link(a, hard)
            alias = root / 'alias';alias.symlink_to(root)
            link = root / 'link.jpg';link.symlink_to(a)
            def doc(*paths): return {**example('exiftool-variant.json'), 'photos': [{'id': f'p{i}', 'path': str(path)} for i, path in enumerate(paths)]}
            same = dict(photo='p1', firstPhoto='p0')
            self.fault(lambda: adaptor.plan(doc(a, a)), 'DUPLICATE_PHOTO_SOURCE', '$.photos[1].path', **same)
            self.fault(lambda: adaptor.plan(doc(a, str(root) + '/./a.jpg')), 'DUPLICATE_PHOTO_SOURCE', '$.photos[1].path', **same)
            self.fault(lambda: adaptor.plan(doc(a, str(root) + '//a.jpg')), 'DUPLICATE_PHOTO_SOURCE', '$.photos[1].path', **same)
            original = adaptor.bounded
            adaptor.bounded = lambda *args, **kw: self.fail('file content was read before the identity and budget checks finished')
            try:
                self.fault(lambda: adaptor.capture_photos(adaptor.plan(doc(a, alias / 'a.jpg'))), 'DUPLICATE_PHOTO_SOURCE', '$.photos[1].path', observed='same device and inode', **same)
                self.fault(lambda: adaptor.capture_photos(adaptor.plan(doc(a, hard))), 'DUPLICATE_PHOTO_SOURCE', '$.photos[1].path', observed='same device and inode', **same)
                self.fault(lambda: adaptor.capture_photos(adaptor.plan(doc(a, link))), 'INVALID_PHOTO_SOURCE', '$.photos[1].path')
                big = []
                for index in range(6):
                    path = root / f'big{index}.jpg';path.write_bytes(b'');os.truncate(path, 3 * 1024 * 1024);big.append(path)
                self.fault(lambda: adaptor.capture_photos(adaptor.plan(doc(*big))), 'PHOTO_RESOURCE_LIMIT', '$.photos[5].path')
                huge = root / 'huge.jpg';huge.write_bytes(b'');os.truncate(huge, 9 * 1024 * 1024)
                self.fault(lambda: adaptor.capture_photos(adaptor.plan(doc(a, huge))), 'PHOTO_RESOURCE_LIMIT', '$.photos[1].path')
            finally: adaptor.bounded = original
            captured = adaptor.capture_photos(adaptor.plan(doc(a, copy)))  # distinct regular files with identical bytes are allowed
            self.assertEqual(len(captured), 2)
            self.assertEqual(captured[0][1]['sha256'], captured[1][1]['sha256'])
            self.fault(lambda: adaptor.bounded(a, 'INVALID_PHOTO_SOURCE', adaptor.PHOTO_LIMIT, location='x', identity=(0, 0)), 'INVALID_PHOTO_SOURCE', 'x')

    def test_numeric_looking_text_must_keep_its_exact_token(self):
        p = adaptor.plan({**example('exiftool-variant.json'), 'photos': [{'id': 'a', 'path': '/x/a.jpg'}]})
        facts = [self.parse(author.build(8, 8, make='1.50', model='5'))]
        row = {'SourceFile': 'captured/a.jpg', 'File:ImageWidth': 8, 'File:ImageHeight': 8, 'File:EncodingProcess': 0, 'File:BitsPerSample': 8, 'File:ColorComponents': 3}
        text = ('[' + json.dumps({**row, 'IFD0:Make': 0, 'IFD0:Model': 0})[:-1].replace('"IFD0:Make": 0', '"IFD0:Make": 1.50').replace('"IFD0:Model": 0', '"IFD0:Model": 5') + '}]').encode()
        self.assertEqual(len(adaptor.compare_native(text, p, facts)), 1)
        self.fault(lambda: adaptor.compare_native(text.replace(b'1.50', b'1.5'), p, facts), 'NATIVE_OBSERVATION_MISMATCH', '$.photos[0].IFD0:Make')


if __name__ == '__main__':
    unittest.main()
