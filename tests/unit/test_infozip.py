"""Info-ZIP publication bundle contract: planning, closed name grammar, strict stored-ZIP reader, discovery and guidance (host only).

Nothing here starts a native process. ``test_infozip_fakes.build_zip`` writes the canonical archive independently, so the
strict reader is exercised against literal bytes and single-field corruptions; the fake native boundary is
test_infozip_native_boundary.py and real Info-ZIP acceptance is tools/qualify_infozip.py.
"""
import copy
import json
import os
from pathlib import Path
import struct
import sys
import tempfile
import tracemalloc
import unittest
import zipfile

from schemaxis.adaptors import registry
from schemaxis.adaptors.infozip import adaptor
from schemaxis.core.faults import SchemaxisError

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_infozip_fakes import build_zip, layout   # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
MEMBERS = [('report.txt', b'hello\n'), ('empty.json', b''), ('tone.wav', bytes(range(256))), ('manifest.json', b'{}\n')]


def document(*names):
    return {'version': 'schemaxis.infozip/1', 'operation': 'bundle', 'files': [{'name': n, 'source': '/tmp/' + n} for n in names or ('a.txt',)]}


class InfozipContract(unittest.TestCase):
    def fault(self, action, code):
        with self.assertRaises(SchemaxisError) as caught:
            action()
        self.assertEqual(caught.exception.fault.code, code, caught.exception.fault.to_dict())
        return caught.exception.fault

    def archive(self, **changes):
        return build_zip(MEMBERS, **changes)

    def rejected(self, data, expected=MEMBERS, code='INVALID_INFOZIP_ARCHIVE'):
        return self.fault(lambda: adaptor.parse_archive(data, expected), code)

    # ------------------------------------------------------------ registration and planning
    def test_registered_with_one_native_option_and_no_framework_branch(self):
        item = registry.ADAPTORS['infozip']
        self.assertEqual([o['dest'] for o in item['cliOptions']], ['infozip'])
        self.assertEqual(item['executables'], ['infozip'])
        self.assertEqual(item['routes']['schemaxis.infozip/1']['acceptedArtifacts'], ['file', 'text', 'image'])
        self.assertEqual(registry.query(document())['adaptors'][0]['operations'], ['bundle'])

    def test_declared_native_string_names_every_fixed_flag(self):
        native = adaptor.DECLARATIONS['bundle']['native']
        for flag in adaptor.ARGUMENTS + ['-v', adaptor.MANIFEST]:
            self.assertIn(flag, native.replace(';', ' ').split())

    def test_planning_is_immutable_deterministic_and_closed(self):
        source = document('report.txt', 'captions.srt')
        before = copy.deepcopy(source)
        prepared = adaptor.plan(source)
        self.assertEqual(before, source)
        self.assertEqual(prepared, adaptor.plan(source))
        self.assertEqual(prepared['native']['arguments'], ['-X', '-0', '-q', 'bundle.zip', 'report.txt', 'captions.srt', 'manifest.json'])
        self.assertEqual(prepared['budget']['maxTotalBytes'], 64 * 1024 * 1024)
        for key in ('compression', 'password', 'level', 'flags', 'recursive', 'comment', 'command', 'exclude'):
            self.fault(lambda: adaptor.plan({**source, key: 1}), 'UNKNOWN_ARGUMENT')
        self.fault(lambda: adaptor.plan({**source, 'files': [{'name': 'a.txt', 'source': '/tmp/a', 'mode': 1}]}), 'UNKNOWN_ARGUMENT')
        for bad in ('Bundle', '', None, 7, ['bundle'], {'a': 1}):
            self.assertEqual(self.fault(lambda: adaptor.plan({**source, 'operation': bad}), 'UNKNOWN_FILTER').location, '$.operation')
        self.fault(lambda: adaptor.plan({**source, 'version': 'schemaxis.infozip/2'}), 'UNSUPPORTED_VERSION')
        self.fault(lambda: adaptor.resources(source, {'threads': 2}, 'op'), 'INVALID_EXECUTION')

    def test_file_count_and_value_types_are_closed(self):
        self.fault(lambda: adaptor.plan({**document(), 'files': []}), 'INVALID_ARGUMENT')
        names = ['f%d.txt' % i for i in range(17)]
        self.fault(lambda: adaptor.plan(document(*names)), 'INVALID_ARGUMENT')
        self.assertEqual(len(adaptor.plan(document(*names[:16]))['files']), 16)
        for value in (None, 'a.txt', {'name': 'a.txt', 'source': '/tmp/a'}, [None], [['a.txt']], [{'name': 'a.txt'}], [{'source': '/tmp/a'}],
                      [{'name': 1, 'source': '/tmp/a'}], [{'name': 'a.txt', 'source': True}], [{'name': 'a.txt', 'source': ['/tmp/a']}]):
            with self.assertRaises(SchemaxisError):
                adaptor.plan({**document(), 'files': value})

    def test_member_name_grammar_is_closed(self):
        for name in ('a.txt', 'report-2_final.json', 'x' * 48 + '.pdf', 'q9.flac', 'captions.vtt', 'a.m4a', 'a.png', 'a.html', 'a.docx', 'a.epub', 'narration.wav'):
            self.assertEqual(adaptor.plan(document(name))['files'][0]['name'], name)
        bad = ['A.txt', 'a.TXT', '1a.txt', '-a.txt', '_a.txt', '.a.txt', 'a', 'a.', '.txt', 'a.zip', 'a.exe', 'a.tar.gz', 'a.b.txt', 'a b.txt', 'a/b.txt',
               'a\\b.txt', '../a.txt', '/a.txt', 'a\x00.txt', 'a\n.txt', 'a.txt\n', '\u00e9.txt', 'a\u00e9.txt', '\uff41.txt', 'x' * 49 + '.txt', 'manifest.json', 'a.jsonx',
               'a.txt ', ' a.txt', 'a\x7f.txt', 'a:b.txt', 'a*.txt', 'a?.txt', 'a\u202e.txt', 'a.txt.', 'a..txt',
               'con.txt', 'prn.json', 'aux.pdf', 'nul.json', 'com1.txt', 'com9.srt', 'lpt1.txt', 'lpt9.vtt']
        for name in ('console.txt', 'con-1.txt', 'nul_.json', 'com0.txt', 'com10.txt', 'lpt.txt', 'aux2.pdf', 'prn1.txt', 'xcon.txt'):   # only the exact device basename is reserved
            self.assertEqual(adaptor.plan(document(name))['files'][0]['name'], name)
        for name in bad:
            fault = self.fault(lambda: adaptor.plan({**document(), 'files': [{'name': name, 'source': '/tmp/a'}]}), 'INVALID_INFOZIP_NAME')
            self.assertEqual(fault.location, '$.files[0].name', repr(name))
        self.fault(lambda: adaptor.plan({**document(), 'files': [{'name': '', 'source': '/tmp/a'}]}), 'INVALID_ARGUMENT')
        self.fault(lambda: adaptor.plan({**document(), 'files': [{'name': 'x' * 60 + '.txt', 'source': '/tmp/a'}]}), 'INVALID_ARGUMENT')   # over the declared length

    def test_duplicates_reserved_names_and_source_paths(self):
        self.assertEqual(self.fault(lambda: adaptor.plan(document('a.txt', 'a.txt')), 'INVALID_INFOZIP_NAME').location, '$.files[1].name')
        self.assertEqual(self.fault(lambda: adaptor.plan(document('manifest.json')), 'INVALID_INFOZIP_NAME').location, '$.files[0].name')
        for source in ('relative/a.txt', 'a.txt', './a.txt', 'https://example.org/a.txt', 'file:///tmp/a.txt', '~/a.txt', '/tmp/a\0'):
            bad = {**document(), 'files': [{'name': 'a.txt', 'source': source}]}
            self.assertEqual(self.fault(lambda: adaptor.plan(bad), 'INVALID_INFOZIP_SOURCE').location, '$.files[0].source', source)
        for name, code in (('infozip-invalid-source.json', 'INVALID_INFOZIP_SOURCE'), ('infozip-invalid-name.json', 'INVALID_INFOZIP_NAME')):
            self.fault(lambda: adaptor.plan(json.loads((ROOT / 'examples/schemaxis' / name).read_text())), code)

    def test_planning_performs_no_file_input_or_output(self):
        with tempfile.TemporaryDirectory() as scratch:
            missing = str(Path(scratch) / 'absent' / 'a.txt')
            before = sorted(Path(scratch).iterdir())
            plan = adaptor.plan({**document(), 'files': [{'name': 'a.txt', 'source': missing}]})
            self.assertEqual(plan['files'][0]['source'], missing)
            self.assertEqual(before, sorted(Path(scratch).iterdir()))
            self.assertFalse(Path(missing).parent.exists())

    def test_runtime_never_uses_path_and_requires_an_absolute_executable(self):
        for value in ('zip', 'bin/zip', '/nonexistent/zip', str(ROOT)):
            fault = self.fault(lambda: adaptor.runtime(value), 'INTERPRETER_NOT_FOUND')
            self.assertEqual(fault.location, '$.runtime.infozip')

    def test_identity_accepts_only_zip_3_0(self):
        banner = 'Copyright (c) 1990-2008 Info-ZIP - Type \'zip "-L"\' for software license.\nThis is Zip 3.0 (July 5th 2008), by Info-ZIP.\nmore\n'
        self.assertEqual(adaptor.check_identity(banner), 'This is Zip 3.0 (July 5th 2008), by Info-ZIP.')
        self.assertEqual(adaptor.check_identity('This is Zip 3.0 (July 7th 2008), by Info-ZIP.\n'), 'This is Zip 3.0 (July 7th 2008), by Info-ZIP.')
        for text in ('This is Zip 2.32 (June 19th 2006), by Info-ZIP.\n', 'This is Zip 3.1 (January 1st 2030), by Info-ZIP.\n', 'This is Zip 3.00 (July 5th 2008), by Info-ZIP.\n'):
            self.fault(lambda: adaptor.check_identity(text), 'UNSUPPORTED_RUNTIME')
        for text in ('', 'bsdtar 3.7\n', 'zip 3.0\n', banner + banner):
            self.fault(lambda: adaptor.check_identity(text), 'UNSUPPORTED_RUNTIME')

    def test_host_contract_guidance_and_curated_search(self):
        from schemaxis.adaptor_conformance import host
        from schemaxis.capabilities import CapabilityCatalogue
        from schemaxis.search_acceptance import check_cases
        from schemaxis.studio_guidance import audit
        self.assertTrue(host(adaptor.VERSION)['verified'])
        self.assertTrue(audit('infozip')['complete'])
        self.assertTrue(check_cases(CapabilityCatalogue(providers=['infozip']), 'infozip')['complete'])

    def test_schema_carries_the_name_pattern_and_bounds(self):
        files = adaptor.schema()['properties']['files']
        self.assertEqual((files['minItems'], files['maxItems']), (1, 16))
        pattern = files['items']['properties']['name']['pattern']
        import re
        self.assertIsNotNone(re.search(pattern, 'report.txt'))
        self.assertIsNone(re.search(pattern, 'Report.txt'))
        for name in ('con.txt', 'nul.json', 'aux.pdf', 'lpt1.txt', 'com9.srt'):         # Windows reserved device basenames are refused by the schema as well
            self.assertIsNone(re.search(pattern, name), name)
        for name in ('console.txt', 'com0.txt', 'lpt.txt'):
            self.assertIsNotNone(re.search(pattern, name), name)
        self.assertEqual(files['items']['required'], ['name', 'source'])

    # ------------------------------------------------------------ manifest
    def test_manifest_is_canonical_ascii_unsigned_and_not_self_referential(self):
        records = adaptor.member_records(['a.txt', 'b.json'], [b'x', b''])
        data = adaptor.manifest_bytes(records)
        document_ = json.loads(data)
        self.assertEqual(data, adaptor.manifest_bytes(records))
        self.assertTrue(data.isascii() and data.endswith(b'\n'))
        self.assertEqual([m['name'] for m in document_['members']], ['a.txt', 'b.json'])
        self.assertEqual(document_['members'][1], {'bytes': 0, 'name': 'b.json', 'sha256': 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855'})
        self.assertIn('Unsigned inventory', document_['inventory'])
        self.assertNotIn('manifest.json', [m['name'] for m in document_['members']])
        self.assertNotIn(adaptor.sha(data), data.decode())
        self.assertLess(len(adaptor.manifest_bytes(adaptor.member_records(['n' * 48 + '.json'] * 16, [b''] * 16))), adaptor.MAX_MANIFEST_BYTES)

    # ------------------------------------------------------------ strict reader: accepted archive
    def test_reader_accepts_the_canonical_archive_and_agrees_with_zipfile(self):
        data = self.archive()
        members = adaptor.parse_archive(data, MEMBERS)
        self.assertEqual([m['name'] for m in members], [n for n, _ in MEMBERS])
        self.assertEqual([m['bytes'] for m in members], [len(d) for _, d in MEMBERS])
        self.assertEqual([m['offset'] for m in members], layout(MEMBERS)['local'])
        with tempfile.TemporaryDirectory() as scratch:
            path = Path(scratch) / 'x.zip'
            path.write_bytes(data)
            with zipfile.ZipFile(path) as archive:
                self.assertEqual([(i.filename, archive.read(i)) for i in archive.infolist()], MEMBERS)
        self.assertEqual(adaptor.parse_archive(data)[0]['name'], 'report.txt')                      # structure alone, without expected bytes

    def test_reader_refuses_windows_reserved_member_names(self):
        for name in ('con.txt', 'prn.json', 'aux.pdf', 'nul.json', 'com1.txt', 'com9.srt', 'lpt1.txt', 'lpt9.vtt'):
            members = [(name, b'x'), ('manifest.json', b'{}\n')]
            self.rejected(build_zip(members), members)
            self.rejected(build_zip(members), None)
        ordinary = [('console.txt', b'x'), ('manifest.json', b'{}\n')]
        self.assertEqual([m['name'] for m in adaptor.parse_archive(build_zip(ordinary), ordinary)], ['console.txt', 'manifest.json'])

    def test_reader_rejects_every_physical_defect(self):
        good, where = self.archive(), layout(MEMBERS)
        local1, central1, end = where['local'][1], where['central'][1], where['end']
        def patch(offset, fmt, value, source=good):
            data = bytearray(source)
            struct.pack_into(fmt, data, offset, value)
            return bytes(data)
        cases = {
            'prefix': b'x' + good, 'suffix': good + b'\0', 'truncated': good[:-1], 'empty': b'', 'short': good[:21],
            'comment declared': patch(end + 20, '<H', 1), 'comment present': build_zip(MEMBERS, comment=b'c'),
            'eocd signature': patch(end, '<I', 0), 'second disk': patch(end + 4, '<H', 1), 'central disk': patch(end + 6, '<H', 1),
            'count mismatch': patch(end + 8, '<H', 3), 'total mismatch': patch(end + 10, '<H', 3), 'zero entries': patch(end + 10, '<H', 0),
            'zip64 count': patch(end + 10, '<H', 0xffff), 'zip64 directory size': patch(end + 12, '<I', 0xffffffff), 'zip64 offset': patch(end + 16, '<I', 0xffffffff),
            'directory offset moved': patch(end + 16, '<I', where['directory'] - 1), 'directory size short': patch(end + 12, '<I', end - where['directory'] - 1),
            'central signature': patch(central1, '<I', 0), 'central made-by': patch(central1 + 4, '<H', 0x0314), 'central needed': patch(central1 + 6, '<H', 20),
            'encrypted flag': patch(central1 + 8, '<H', 1), 'descriptor flag': patch(central1 + 8, '<H', 8), 'utf8 flag': patch(central1 + 8, '<H', 0x800),
            'deflate method': patch(central1 + 10, '<H', 8), 'central time': patch(central1 + 12, '<H', 2), 'central date': patch(central1 + 14, '<H', 0x2821),
            'central crc': patch(central1 + 16, '<I', 1), 'central compressed size': patch(central1 + 20, '<I', 1), 'central size': patch(central1 + 24, '<I', 1),
            'central extra': patch(central1 + 30, '<H', 4), 'central comment': patch(central1 + 32, '<H', 1), 'central disk number': patch(central1 + 34, '<H', 1),
            'internal attributes': patch(central1 + 36, '<H', 1), 'symlink attributes': patch(central1 + 38, '<I', (0o120777) << 16), 'mode 0644': patch(central1 + 38, '<I', (0o100644) << 16),
            'directory attributes': patch(central1 + 38, '<I', (0o040755) << 16), 'central offset gap': patch(central1 + 42, '<I', local1 + 1),
            'central offset overlap': patch(central1 + 42, '<I', local1 - 1), 'local signature': patch(local1, '<I', 0), 'local needed': patch(local1 + 4, '<H', 20),
            'local flags': patch(local1 + 6, '<H', 8), 'local method': patch(local1 + 8, '<H', 8), 'local time': patch(local1 + 10, '<H', 1), 'local crc': patch(local1 + 14, '<I', 7),
            'local size': patch(local1 + 18, '<I', 1), 'local extra': patch(local1 + 28, '<H', 1), 'local name length': patch(local1 + 26, '<H', 3),
            'data byte flipped': good[:where['local'][2] + 30 + len('tone.wav') + 5] + b'\xff' + good[where['local'][2] + 30 + len('tone.wav') + 6:],
        }
        for label, data in cases.items():
            with self.subTest(label):
                self.rejected(data)

    def test_reader_rejects_gaps_overlaps_reordering_duplicates_and_unsafe_names(self):
        gap = build_zip(MEMBERS)
        where = layout(MEMBERS)
        gapped = gap[:where['local'][1]] + b'\0\0' + gap[where['local'][1]:]
        self.rejected(gapped)
        reordered = [MEMBERS[1], MEMBERS[0], MEMBERS[2], MEMBERS[3]]
        self.rejected(build_zip(reordered))                                           # order differs from the captured files
        self.rejected(build_zip(MEMBERS[:-1] + [('report.txt', b'x')] + MEMBERS[-1:]), expected=None)           # duplicate name
        self.rejected(build_zip(MEMBERS[:-1]), expected=None)                         # manifest.json absent
        self.rejected(build_zip([MEMBERS[3]] + MEMBERS[:3]), expected=None)           # manifest.json not last
        self.rejected(build_zip(MEMBERS + [('manifest.json', b'again')]), expected=None)
        for name in ('../report.txt', '/etc/passwd', 'dir/a.txt', 'a\\b.txt', 'A.txt', 'a.TXT', 'a.zip', '-a.txt', 'a b.txt', 'a..txt', 'x' * 60 + '.txt', 'a.txt/'):
            with self.subTest(name):
                self.rejected(build_zip([(name, b'x'), MEMBERS[3]]), expected=None)
        self.rejected(build_zip([('é.txt'.encode('utf-8').decode('latin-1'), b'x'), MEMBERS[3]]), expected=None)
        self.rejected(build_zip(MEMBERS + [(n, b'') for n in ('a%d.txt' % i for i in range(16))]), expected=None)    # over seventeen entries

    def test_reader_compares_every_byte_and_the_member_list(self):
        flipped = [(n, d) for n, d in MEMBERS]
        flipped[2] = ('tone.wav', bytes(range(256))[:-1] + b'\x00')
        self.rejected(build_zip(MEMBERS), expected=flipped)
        self.rejected(build_zip(MEMBERS), expected=MEMBERS[:-1])
        self.rejected(build_zip(MEMBERS), expected=[('other.txt', b'hello\n')] + MEMBERS[1:])
        self.rejected(build_zip(MEMBERS), expected=[MEMBERS[0], ('empty.json', b'x')] + MEMBERS[2:])
        import io
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as archive:
            for name, data in MEMBERS:
                archive.writestr(name, data)
        self.rejected(buffer.getvalue())
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_STORED) as archive:
            for name, data in MEMBERS:
                archive.writestr(name, data)
        self.rejected(buffer.getvalue())                                               # stored, but not the canonical header values

    def test_hostile_fields_never_size_an_allocation_or_a_loop(self):
        """Tiny archives declaring 4 GiB sizes, counts and offsets are refused by arithmetic, without allocating to them."""
        where = layout(MEMBERS)
        hostile = []
        for offset, fmt in ((where['central'][0] + 20, '<I'), (where['central'][0] + 24, '<I'), (where['local'][0] + 18, '<I'), (where['local'][0] + 22, '<I')):
            data = bytearray(self.archive())
            struct.pack_into(fmt, data, offset, 0xfffffff0)
            hostile.append(bytes(data))
        for offset, fmt, value in ((where['end'] + 8, '<H', 65534), (where['end'] + 10, '<H', 65534), (where['end'] + 12, '<I', 0xfffffff0), (where['end'] + 16, '<I', 0xfffffff0),
                                   (where['central'][0] + 28, '<H', 65535), (where['central'][0] + 42, '<I', 0xfffffff0)):
            data = bytearray(self.archive())
            struct.pack_into(fmt, data, offset, value)
            hostile.append(bytes(data))
        tracemalloc.start()
        try:
            for data in hostile:
                self.rejected(data, expected=None)
            peak = tracemalloc.get_traced_memory()[1]
        finally:
            tracemalloc.stop()
        self.assertLess(peak, 1024 * 1024, 'hostile headers must not allocate in proportion to their declared sizes')
        self.assertTrue(all(len(data) < 1024 for data in hostile))
        self.rejected(bytes(adaptor.MAX_ARCHIVE_BYTES + 1), code='INFOZIP_BUDGET')

    def test_reader_is_a_pure_function_of_the_bytes(self):
        data = self.archive()
        self.assertEqual(adaptor.parse_archive(data, MEMBERS), adaptor.parse_archive(bytes(data), copy.deepcopy(MEMBERS)))

    # ------------------------------------------------------------ strict JSON and typed comparison
    def test_strict_json_refuses_duplicates_constants_overflow_bom_and_depth(self):
        self.assertEqual(adaptor.strict_json(b'{"a": 1}', 'x'), {'a': 1})
        for text in (b'{"a":1,"a":2}', b'{"a":NaN}', b'{"a":Infinity}', b'{"a":-Infinity}', b'{"a":1e400}', b'\xef\xbb\xbf{"a":1}', b'\xff', b'{', b'[' * 100000):
            self.fault(lambda: adaptor.strict_json(text, 'x'), 'VERIFICATION_FAILED')
        self.assertFalse(adaptor.same_json({'a': True}, {'a': 1}))
        self.assertFalse(adaptor.same_json({'a': 66}, {'a': 66.0}))
        self.assertTrue(adaptor.same_json({'b': [1], 'a': 2}, {'a': 2, 'b': [1]}))

    # ------------------------------------------------------------ bounded reads
    def test_source_reads_refuse_special_files_symlinks_and_oversize(self):
        with tempfile.TemporaryDirectory() as scratch:
            scratch = Path(scratch)
            (scratch / 'a.txt').write_bytes(b'abc')
            (scratch / 'link').symlink_to(scratch / 'a.txt')
            (scratch / 'dir').mkdir()
            os.mkfifo(scratch / 'fifo')
            self.assertEqual(adaptor.read_source(str(scratch / 'a.txt'), 'x'), b'abc')
            for target in ('link', 'dir', 'fifo', 'absent'):
                self.assertEqual(self.fault(lambda: adaptor.read_source(str(scratch / target), '$.files[0].source'), 'INVALID_INFOZIP_SOURCE').location, '$.files[0].source')
            self.fault(lambda: adaptor.read_source('/dev/null', 'x'), 'INVALID_INFOZIP_SOURCE')
            self.fault(lambda: adaptor.read_source('/dev/zero', 'x'), 'INVALID_INFOZIP_SOURCE')
            (scratch / 'big.txt').write_bytes(bytes(2049))
            (scratch / 'small.txt').write_bytes(bytes(1024))
            original = adaptor.MAX_MEMBER_BYTES, adaptor.MAX_TOTAL_BYTES
            adaptor.MAX_MEMBER_BYTES, adaptor.MAX_TOTAL_BYTES = 2048, 2500
            try:
                self.fault(lambda: adaptor.read_source(str(scratch / 'big.txt'), 'x'), 'INFOZIP_BUDGET')
                files = [{'name': 'a%d.txt' % i, 'source': str(scratch / 'small.txt')} for i in range(3)]
                self.assertEqual(len(adaptor.read_sources(files[:2])), 2)
                self.assertEqual(self.fault(lambda: adaptor.read_sources(files), 'INFOZIP_BUDGET').location, '$.files[2].source')
            finally:
                adaptor.MAX_MEMBER_BYTES, adaptor.MAX_TOTAL_BYTES = original

    def test_reuse_identity_is_the_source_byte_digest(self):
        with tempfile.TemporaryDirectory() as scratch:
            path = Path(scratch) / 'a.txt'
            path.write_bytes(b'one')
            doc = {**document(), 'files': [{'name': 'a.txt', 'source': str(path)}]}
            first = adaptor.reusableInputs(doc)
            self.assertEqual(first, {str(path): adaptor.sha(b'one')})
            path.write_bytes(b'two')
            self.assertNotEqual(first, adaptor.reusableInputs(doc))
            path.unlink()
            self.fault(lambda: adaptor.reusableInputs(doc), 'INVALID_INFOZIP_SOURCE')


if __name__ == '__main__':
    unittest.main()
