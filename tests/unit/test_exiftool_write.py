"""Host and native tests of the ExifTool metadata write family (editMetadata, removeMetadata).

Host tests need no native process. Native tests need a real ExifTool 13.55 through SCHEMAXIS_EXIFTOOL and are skipped otherwise; every
expected value is a literal written here, never taken from ExifTool or from the code under test.
"""
import copy
import hashlib
import json
import os
from pathlib import Path
import random
import shutil
import struct
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(ROOT / 'tools'))

import author_exiftool_fixtures as author  # noqa: E402
from schemaxis.adaptors.exiftool import adaptor, catalogue, codecs, containers, edits, editing, jpegwrite, listing, proofs, records, removal, workbench, writes  # noqa: E402
from schemaxis.core.faults import SchemaxisError  # noqa: E402

FIXTURES = ROOT / 'examples/schemaxis/fixtures/exiftool'
FILES = author.edit_files()
# Plan hashes of the retained E1 read examples, computed with the accepted E1 source before any write-family change (hard-coded, not recomputed).
E1_PLAN_HASHES = {'exiftool-audit-baseline.json': '8b9ab9abefc28518b618653f755406ce40e922bcd1857d7686047abfc4cf9752',
                  'exiftool-baseline.json': 'c5119bc8968c31737f0a4b047328bb0591147a166a99546abeaf4682b718971f',
                  'exiftool-compare-baseline.json': '4d4d522dcccb730a8323feb0287fcd4df8f5680d00331c3740c2147ce2bcd447',
                  'exiftool-inspect-baseline.json': 'e0e96ffbdf7596fb20bde076ed902e07c55d710f00c7bf06759024b8b974b7a3',
                  'exiftool-inspect-variant.json': '3d5a90bfda75be70a14354d11b8af1c9f09940f016d0bf3230d619a1ed23b129',
                  'exiftool-variant.json': 'f64a1056d09a83b092af902a1a0fadf9e495c06e9c5b88a89efb22fcd3cbc483'}


def doc(operation, items, **rest):
    return {'version': 'schemaxis.exiftool/1', 'operation': operation, 'media': {'items': items}, **rest}


class Base(unittest.TestCase):
    def fault(self, call, code, location=None):
        with self.assertRaises(SchemaxisError) as caught:
            call()
        self.assertEqual(caught.exception.fault.code, code)
        if location is not None:
            self.assertEqual(caught.exception.fault.location, location)
        return caught.exception.fault

    def item(self, name):
        data = FILES[name]
        located = containers.locate(data)
        return {'bytes_': data, 'walk': jpegwrite.walk(data), 'located': located, 'payloads': records.Payloads(located)}


class Catalogues(Base):
    def test_known_catalogues_are_pinned_and_differ_only_at_the_creator_codec(self):
        self.assertEqual(catalogue.digest(catalogue.VERSION), '1785f956c2ad54c301eb7e9558790018d2b4ccd3adce2c91c3f7334b4d296c67')
        a, b = catalogue.catalogue(catalogue.VERSION), catalogue.catalogue(catalogue.VERSION_MWG)
        self.assertEqual(b['version'], 'schemaxis.exiftool.fields/2')
        a2 = copy.deepcopy(b)
        a2['version'] = a['version']
        a2['fields']['creator']['sources'][0]['codec'] = 'exifText'
        self.assertEqual(a2, a)
        self.assertEqual(b['fields']['creator']['sources'][0]['codec'], 'exifArtistList')

    def test_a_changed_catalogue_byte_fails_closed(self):
        saved = dict(catalogue.KNOWN)
        try:
            catalogue.KNOWN[catalogue.VERSION] = (saved[catalogue.VERSION][0], '0' * 64)
            with self.assertRaises(catalogue.CatalogueError) as caught:
                catalogue.digest()
            self.assertIn('CATALOGUE_DIGEST_DRIFT', str(caught.exception))
            with self.assertRaises(catalogue.CatalogueError):
                catalogue.digest('schemaxis.exiftool.fields/9')
        finally:
            catalogue.KNOWN.update(saved)
        self.assertEqual(writes.digest(), writes.PIN)

    def test_writes_data_collides_nowhere_and_every_destination_has_an_independent_reader(self):
        data = writes.load()
        names = [d['write'] for f in data['fields'].values() for d in f['destinations']]
        self.assertEqual(len(names), len(set(names)))
        broken = copy.deepcopy(data)
        broken['fields']['rating']['destinations'].append(dict(broken['fields']['title']['destinations'][0], role='companion'))
        with self.assertRaises(writes.WritesError):
            writes.validate(broken)
        touching = copy.deepcopy(data)
        touching['removalCategories']['location']['native']['observed'].append({'group1': 'IFD0', 'names': ['Orientation']})
        with self.assertRaises(writes.WritesError):
            writes.validate(touching)
        rendering = copy.deepcopy(data)
        rendering['removalCategories']['rights']['xmp'].append('tiff:Orientation')
        with self.assertRaises(writes.WritesError):
            writes.validate(rendering)

    def test_creator_interpretation_selects_the_catalogue_and_the_default_plan_never_changes(self):
        base = json.loads((ROOT / 'examples/schemaxis/exiftool-inspect-baseline.json').read_text())
        plain, literal, mwg = workbench.plan(base), workbench.plan({**base, 'creatorInterpretation': 'literal'}), workbench.plan({**base, 'creatorInterpretation': 'mwg'})
        self.assertEqual(plain, literal)
        self.assertEqual(plain['catalogue']['version'], 'schemaxis.exiftool.fields/1')
        self.assertEqual(mwg['catalogue']['version'], 'schemaxis.exiftool.fields/2')
        self.assertNotEqual(adaptor.plan_hash(plain), adaptor.plan_hash(mwg))
        for name, wanted in E1_PLAN_HASHES.items():
            self.assertEqual(adaptor.plan_hash(adaptor.plan(json.loads((ROOT / 'examples/schemaxis' / name).read_text()))), wanted, name)

    def test_artist_lists_follow_the_mwg_join_and_refuse_what_does_not_round_trip(self):
        split = codecs.artist_split
        self.assertEqual(split('Ana Núñez; "Smith; Jones"; Li, Wei'), ('Ana Núñez', 'Smith; Jones', 'Li, Wei'))
        self.assertEqual(split('Smith;Jones'), ('Smith;Jones',))
        self.assertEqual(split('A;  B'), ('A', ' B'))
        self.assertEqual(split('Solo'), ('Solo',))
        for bad in ('A; ', '"A; B', '"Q"', '"He said ""hi"""; X'):
            with self.assertRaises(codecs.ValueProblem) as caught:
                split(bad)
            self.assertEqual(caught.exception.code, 'EXIF_ARTIST_NONCANONICAL', bad)
        for items in (('A', 'B'), ('Smith; Jones', 'x'), ('"quoted" start', 'y'), ('say "hi"',)):
            self.assertEqual(split(codecs.artist_join(items)), items)


class Walker(Base):
    def test_every_authored_fixture_is_admitted_with_its_frame_and_scans(self):
        expect = {'edit-rich.jpg': ('baseline', 1), 'edit-progressive.jpg': ('progressive', 10), 'edit-restart.jpg': ('baseline', 1), 'edit-multiscan.jpg': ('baseline', 3)}
        for name, data in FILES.items():
            if name == 'edit-trailer.jpg':
                continue
            walk = jpegwrite.walk(data)
            if name in expect:
                self.assertEqual((walk['frame']['process'], walk['scans']), expect[name], name)
        self.assertEqual(FILES['edit-progressive.jpg'].count(b'\xff\xda'), 10)

    def test_refusals_have_stable_codes(self):
        data = FILES['edit-jfif-only.jpg']
        sos = data.index(b'\xff\xda')
        end = sos + 2 + struct.unpack('>H', data[sos + 2:sos + 4])[0]
        cases = [('trailer', data + b'x', 'WRITE_TRAILER_UNSUPPORTED'), ('app segment after scan', data[:end] + b'\x01\x02\xff\xe1\x00\x04ab\xff\xd9', 'WRITE_TAIL_SEGMENT_UNSUPPORTED'),
                 ('restart out of sequence', data[:end] + b'\xff\xd1\xff\xd9', 'JPEG_RESTART_SEQUENCE_INVALID'), ('no EOI', data[:-2], 'JPEG_TRUNCATED'),
                 ('lossless frame', data.replace(b'\xff\xc0', b'\xff\xc3', 1), 'UNSUPPORTED_JPEG_PROCESS'), ('arithmetic', data.replace(b'\xff\xc0', b'\xff\xc9', 1), 'UNSUPPORTED_JPEG_PROCESS'),
                 ('not a jpeg', b'GIF89a', 'JPEG_SIGNATURE')]
        for name, blob, code in cases:
            with self.assertRaises(jpegwrite.Refused, msg=name) as caught:
                jpegwrite.walk(blob)
            self.assertEqual(caught.exception.code, code, name)
        two_xmp = data.replace(b'\xff\xdb', jpegwrite_segment(0xE1, author.xmp_app1(author.xmp_packet(''))) * 2 + b'\xff\xdb', 1)
        with self.assertRaises(jpegwrite.Refused) as caught:
            jpegwrite.walk(two_xmp)
        self.assertEqual(caught.exception.code, 'XMP_SEGMENT_REPEATED')

    def test_entropy_markers_are_never_mistaken_for_segments(self):
        data = FILES['edit-jfif-only.jpg']
        sos = data.index(b'\xff\xda')
        end = sos + 2 + struct.unpack('>H', data[sos + 2:sos + 4])[0]
        rnd = random.Random(7)
        for _ in range(400):
            entropy, rst = bytearray(), 0
            for _ in range(rnd.randrange(0, 160)):
                roll = rnd.random()
                if roll < .15:
                    entropy += b'\xff\x00'
                elif roll < .27:
                    entropy += bytes([0xFF, 0xD0 + rst % 8]); rst += 1
                else:
                    byte = rnd.randrange(256); entropy.append(byte)
                    if byte == 0xFF: entropy.append(0)
            blob = data[:end] + bytes(entropy) + b'\xff\xff\xff\xd9'
            walk = jpegwrite.walk(blob)
            self.assertEqual((walk['scans'], walk['end']), (1, len(blob)))

    def test_preservation_names_each_kind_of_change(self):
        before = FILES['edit-rich.jpg']
        walk = jpegwrite.walk(before)
        self.assertEqual(jpegwrite.preservation(walk, walk, before, before, set()), [])
        sos = walk['firstScan']

        def codes(blob, declared=()):
            return sorted({p['code'] for p in jpegwrite.preservation(walk, jpegwrite.walk(blob), before, blob, set(declared))})
        scan = bytearray(before)
        scan[sos + 14] ^= 0x40
        self.assertEqual(codes(bytes(scan)), ['IMAGE_DATA_CHANGED'])
        icc = bytearray(before)
        icc[before.index(b'ICC_PROFILE') + 20] ^= 1
        self.assertEqual(codes(bytes(icc)), ['RENDERING_SEGMENT_CHANGED'])
        adobe = bytearray(before)
        adobe[before.index(b'Adobe\0') + 11] ^= 1
        self.assertEqual(codes(bytes(adobe)), ['RENDERING_SEGMENT_CHANGED'])
        table = bytearray(before)
        table[next(x['offset'] for x in walk['pre'] if x['marker'] == 0xDB) + 6] ^= 1
        self.assertEqual(codes(bytes(table)), ['IMAGE_DATA_CHANGED'])
        com = before.replace(b'a synthetic comment', b'a synthetic commenT')
        self.assertEqual(codes(com), ['SEGMENT_CHANGED'])
        self.assertEqual(codes(com, ['comment']), ['SEGMENT_CHANGED'])
        xmp = before.replace(b'Old title</rdf:li>', b'Old titlf</rdf:li>')
        self.assertEqual(codes(xmp), ['UNDECLARED_SEGMENT_CHANGE'])
        self.assertEqual(codes(xmp, ['xmp']), [])


def jpegwrite_segment(marker, body): return bytes([0xFF, marker]) + struct.pack('>H', len(body) + 2) + body


class Planner(Base):
    def plan(self, name, edit_map, **policies):
        item = self.item(name)
        return edits.plan_item({f: edits.normalise_edit(f, e, '$.edits.' + f) for f, e in edit_map.items()}, item['payloads'], edits.normalise_policies(policies), False)

    def refusal(self, name, edit_map, code, **policies):
        with self.assertRaises(edits.Refusal) as caught:
            self.plan(name, edit_map, **policies)
        self.assertEqual(caught.exception.code, code)
        return caught.exception

    def test_value_domain_refuses_what_cannot_read_back_identically(self):
        for value, code in (('', 'EDIT_EMPTY_VALUE'), ('  ', 'EDIT_EMPTY_VALUE'), (' lead', 'EDIT_VALUE_INVALID'), ('trail ', 'EDIT_VALUE_INVALID'), ('a\tb', 'EDIT_VALUE_INVALID'),
                            ('a\nb', 'EDIT_VALUE_INVALID'), ('a￾b', 'EDIT_VALUE_INVALID'), ('a\ud800b', 'EDIT_VALUE_INVALID'), ('x' * 600, 'EDIT_VALUE_TOO_LONG')):
            with self.assertRaises(edits.PlanError, msg=repr(value)) as caught:
                edits.normalise_edit('title', {'set': value}, '$.edits.title')
            self.assertEqual(caught.exception.code, code, repr(value))
        self.assertEqual(edits.normalise_edit('description', {'set': 'a\nb'}, '$')['set']['text'], 'a\nb')
        for bad, code in (({'set': {'text': 't', 'languages': [{'language': 'FR', 'text': 'a'}, {'language': 'fr', 'text': 'b'}]}}, 'EDIT_DUPLICATE_LANGUAGE'),
                          ({'set': {'text': 't', 'languages': [{'language': 'x-default', 'text': 'a'}]}}, 'INVALID_ARGUMENT'), ({'set': {'text': 't', 'languages': [{'language': 'not a tag', 'text': 'a'}]}}, 'INVALID_ARGUMENT')):
            with self.assertRaises(edits.PlanError) as caught:
                edits.normalise_edit('title', bad, '$')
            self.assertEqual(caught.exception.code, code)
        for field, bad, code in (('keywords', {'set': ['a', 'a']}, 'EDIT_DUPLICATE_ITEM'), ('creator', {'add': ['x']}, 'EDIT_INVALID'), ('keywords', {'set': ['a'], 'clear': True}, 'EDIT_INVALID'),
                                 ('rating', {'set': 6}, 'EDIT_VALUE_INVALID'), ('rating', {'set': True}, 'EDIT_VALUE_INVALID'), ('rightsUrl', {'set': 'ftp://x'}, 'EDIT_VALUE_INVALID'), ('keywords', {'add': ['a'], 'remove': ['a']}, 'EDIT_INVALID')):
            with self.assertRaises(edits.PlanError, msg=(field, bad)) as caught:
                edits.normalise_edit(field, bad, '$')
            self.assertEqual(caught.exception.code, code, (field, bad))
        nfd = 'é'
        self.assertEqual(edits.normalise_edit('title', {'set': nfd}, '$')['set']['text'], nfd)   # never normalised

    def test_native_assignments_are_literal_catalogue_names_with_the_value_as_the_whole_argument(self):
        plan = self.plan('edit-rich.jpg', {'title': {'set': {'text': 'Ridge', 'languages': [{'language': 'fr', 'text': 'Crête'}]}}, 'creator': {'set': ['Ana Núñez', 'Smith; Jones']}, 'rating': {'set': 3}, 'keywords': {'clear': True}})
        self.assertEqual(edits.assignments(plan), [
            '-XMP-dc:Title-x-default=Ridge', '-XMP-dc:Title-fr=Crête', '-IPTC:ObjectName=Ridge', '-IPTC:Keywords=', '-XMP-dc:Creator=Ana Núñez', '-XMP-dc:Creator=Smith; Jones',
            '-IPTC:By-line=Ana Núñez', '-IPTC:By-line=Smith; Jones', '-IFD0:Artist=Ana Núñez; "Smith; Jones"', '-XMP-xmp:Rating=3', '-Photoshop:IPTCDigest=new'])
        for value in ('-all=', '<file', '@x', '$HOME', '=x'):
            args = edits.assignments(self.plan('edit-rich.jpg', {'locationCity': {'set': value}}))
            self.assertIn('-XMP-photoshop:City=' + value, args)
            self.assertTrue(all(a.startswith('-') and '=' in a for a in args))

    def test_keyword_add_and_remove_resolve_against_a_concordant_base_only(self):
        plan = self.plan('edit-keywords.jpg', {'keywords': {'add': ['new'], 'remove': ['draft']}})
        self.assertEqual(plan['fields']['keywords']['value'], ['alpine', 'dawn', 'new'])
        self.assertEqual(self.refusal('edit-keywords.jpg', {'keywords': {'remove': ['absent']}}, 'EDIT_ITEM_ABSENT').observed['value'], 'absent')
        self.refusal('edit-keywords.jpg', {'keywords': {'add': ['alpine']}}, 'EDIT_ITEM_PRESENT')
        self.refusal('edit-keywords.jpg', {'keywords': {'remove': ['alpine', 'dawn', 'draft']}}, 'EDIT_EMPTY_VALUE')
        conflict = self.refusal('edit-keywords-conflict.jpg', {'keywords': {'add': ['x']}}, 'EDIT_BASE_CONFLICT')
        self.assertEqual(sorted(conflict.observed['sources']), ['iptc', 'xmp'])
        self.assertEqual(self.plan('edit-keywords-conflict.jpg', {'keywords': {'set': ['x']}})['fields']['keywords']['value'], ['x'])   # set replaces a conflicting base

    def test_other_languages_follow_their_policy_and_clear_lists_what_it_deletes(self):
        title = {'title': {'set': 'Neuer Titel'}}
        kept = self.plan('edit-languages.jpg', title)['fields']['title']
        self.assertEqual(kept['otherLanguages'], {'kept': ['de', 'fr'], 'removed': []})
        removed = self.plan('edit-languages.jpg', title, otherLanguages='remove')
        self.assertIn('-XMP-dc:Title-de=', edits.assignments(removed))
        self.assertIn('-XMP-dc:Title-fr=', edits.assignments(removed))
        self.assertEqual(self.refusal('edit-languages.jpg', title, 'EDIT_OTHER_LANGUAGES_PRESENT', otherLanguages='refuse').observed['languages'], ['de', 'fr'])
        cleared = self.plan('edit-languages.jpg', {'title': {'clear': True}})['fields']['title']
        self.assertEqual(cleared['otherLanguages']['removed'], ['de', 'fr'])
        self.assertIn('-XMP-dc:Title=', edits.assignments(self.plan('edit-languages.jpg', {'title': {'clear': True}})))

    def test_companion_losses_are_decided_before_any_write_and_never_truncate(self):
        long_name = 'é' * 17                       # 34 UTF-8 bytes against the 32-byte By-line
        plan = self.plan('edit-rich.jpg', {'creator': {'set': [long_name]}})
        loss = plan['fields']['creator']['losses']
        self.assertEqual([(x['reason'], x['treatment'], x['limit'], x['bytes']) for x in loss], [('iptcLength', 'companionRemoved', 32, [34])])
        args = edits.assignments(plan)
        self.assertIn('-IPTC:By-line=', args)
        self.assertNotIn('-IPTC:By-line=' + long_name, args)
        self.assertIn('-XMP-dc:Creator=' + long_name, args)                      # the XMP value is always complete
        self.refusal('edit-rich.jpg', {'creator': {'set': [long_name]}}, 'COMPANION_LOSS_REFUSED', companionLoss='refuse')
        ascii_only = self.plan('edit-rich.jpg', {'locationCity': {'set': 'Zürich'}}, exifEncoding='ascii')
        self.assertEqual(ascii_only['fields']['locationCity']['losses'], [])             # no EXIF form exists for city
        desc = self.plan('edit-rich.jpg', {'description': {'set': 'Zoë 🌄'}}, exifEncoding='ascii')
        self.assertEqual([(x['reason'], x['treatment']) for x in desc['fields']['description']['losses']], [('exifNonAscii', 'companionRemoved')])
        self.assertIn('-IFD0:ImageDescription=', edits.assignments(desc))
        editor = self.plan('edit-copyright-editor.jpg', {'copyright': {'set': '(c) 2026'}})
        self.assertEqual([x['reason'] for x in editor['fields']['copyright']['losses']], ['exifCopyrightEditorPart'])

    def test_iptc_character_set_is_assigned_only_where_no_existing_text_changes_meaning(self):
        ascii_set = self.plan('edit-ascii-iptc.jpg', {'creator': {'set': ['Ana Núñez']}})
        self.assertTrue(ascii_set['iptc']['assignCharset'])          # every untouched dataset is ASCII, so UTF-8 can be declared
        self.assertIn('-IPTC:CodedCharacterSet=UTF8', edits.assignments(ascii_set))
        plain = self.plan('edit-ascii-iptc.jpg', {'creator': {'set': ['Plain Name']}})
        self.assertFalse(plain['iptc']['assignCharset'])
        legacy = self.plan('edit-legacy-iptc.jpg', {'creator': {'set': ['Ana Núñez']}})                # an untouched Latin-1 title exists
        self.assertFalse(legacy['iptc']['assignCharset'])
        self.assertEqual([(x['reason'], x['treatment']) for x in legacy['fields']['creator']['losses']], [('iptcCharsetUnknown', 'companionRemoved')])
        self.assertNotIn('-IPTC:CodedCharacterSet=UTF8', edits.assignments(legacy))
        self.refusal('edit-legacy-iptc.jpg', {'creator': {'set': ['Ana Núñez']}}, 'COMPANION_LOSS_REFUSED', companionLoss='refuse')
        none = self.plan('edit-no-iptc.jpg', {'creator': {'set': ['Ana Núñez']}})
        self.assertEqual(none['iptc'], {'state': 'absent', 'charset': None, 'assignCharset': False, 'changed': False, 'created': False, 'digest': False})
        always = self.plan('edit-no-iptc.jpg', {'creator': {'set': ['Ana Núñez']}}, iptc='always')
        self.assertTrue(always['iptc']['created'] and always['iptc']['assignCharset'])

    def test_exif_is_never_created(self):
        plan = self.plan('edit-jfif-only.jpg', {'title': {'set': 'Only XMP'}, 'description': {'set': 'd'}})
        self.assertFalse(plan['declared']['exif'])
        self.assertEqual([d['state'] for d in plan['fields']['description']['destinations']], ['write', 'skip', 'skip'])
        self.assertEqual(edits.assignments(plan), ['-XMP-dc:Title-x-default=Only XMP', '-XMP-dc:Description-x-default=d'])


class Proofs(Base):
    def record(self, rows):
        return {'observations': [{'group0': g0, 'group1': g1, 'name': n, 'instance': 0, 'value': v} for g0, g1, n, v in rows], 'warnings': [], 'errors': [], 'fault': None}

    def test_native_diff_is_closed_and_value_aware(self):
        base = Base()
        item = base.item('edit-rich.jpg')
        plan = edits.plan_item({'title': {'set': {'text': 'T', 'languages': []}}}, item['payloads'], edits.normalise_policies({}), True)
        ctx = {'xmpWritten': True, 'assignCharset': False, 'iptcChanged': True, 'digest': True, 'afterIimMd5': 'a' * 32, 'thumbnailSame': True}
        before = self.record([('XMP', 'XMP-dc', 'Title', 'Old'), ('IFD0', 'IFD0', 'Make', 'N'), ('EXIF', 'IFD1', 'ThumbnailOffset', 486)])
        after = self.record([('XMP', 'XMP-dc', 'Title', 'T'), ('XMP', 'XMP-x', 'XMPToolkit', edits.TOOLKIT), ('IPTC', 'IPTC', 'ObjectName', 'T'), ('Photoshop', 'Photoshop', 'IPTCDigest', 'a' * 32),
                             ('IFD0', 'IFD0', 'Make', 'N'), ('EXIF', 'IFD1', 'ThumbnailOffset', 480)])
        diff = proofs.native_diff(before, after, plan, ctx)
        self.assertEqual(diff['unexplained'], [])
        self.assertEqual(sorted(s['rule'] for s in diff['sideEffects']), ['S3-thumbnailOffset', 'S5-xmpToolkit', 'S7-iptcDigest'])
        # wrong side-effect values are unexplained, not ignored
        for rows, key in ((('XMP', 'XMP-x', 'XMPToolkit', 'Other 1.0'), 'XMP-x'), (('Photoshop', 'Photoshop', 'IPTCDigest', 'b' * 32), 'IPTCDigest')):
            bad = self.record([r for r in [('XMP', 'XMP-dc', 'Title', 'T'), ('XMP', 'XMP-x', 'XMPToolkit', edits.TOOLKIT), ('IPTC', 'IPTC', 'ObjectName', 'T'), ('Photoshop', 'Photoshop', 'IPTCDigest', 'a' * 32), rows] if r[2] != rows[2] or r is rows])
            found = proofs.native_diff(before, bad, plan, ctx)['unexplained']
            self.assertTrue(any(key in u['key'] for u in found), key)
        changed = self.record([('XMP', 'XMP-dc', 'Title', 'T'), ('IFD0', 'IFD0', 'Make', 'Other'), ('EXIF', 'IFD1', 'ThumbnailOffset', 486)])
        self.assertEqual([u['key'] for u in proofs.native_diff(before, changed, plan, ctx)['unexplained']], ['IFD0:IFD0:Make'])
        thumb = proofs.native_diff(before, after, plan, {**ctx, 'thumbnailSame': False})
        self.assertEqual([u['key'] for u in thumb['unexplained']], ['EXIF:IFD1:ThumbnailOffset'])
        renumbered = proofs.native_diff(self.record([('XMP', 'XMP-dc', 'Subject', 'a'), ('XMP', 'XMP-dc', 'Subject', 'b')]), self.record([('XMP', 'XMP-dc', 'Subject', 'b'), ('XMP', 'XMP-dc', 'Subject', 'a')]), {'fields': {}}, ctx)
        self.assertEqual((renumbered['renumbered'], renumbered['unexplained']), (['XMP:XMP-dc:Subject'], []))

    def test_readback_names_wrong_values_shapes_and_untouched_destinations(self):
        base = Base()
        item = base.item('edit-rich.jpg')
        plan = edits.plan_item({'keywords': {'set': ['a', 'b']}, 'title': {'set': {'text': 'T', 'languages': []}}}, item['payloads'], edits.normalise_policies({}), True)
        before, after = {}, {}
        for name, f in plan['fields'].items():
            for d in writes.fields()[name]['destinations']:
                before[(name, d['family'])] = next(x for x in f['destinations'] if x['family'] == d['family'])['before']
                after[(name, d['family'])] = proofs.expected_read(next(x for x in f['destinations'] if x['family'] == d['family']), f, before[(name, d['family'])])
        self.assertEqual(proofs.readback(plan, before, after, '$.items[0]'), [])
        wrong = copy.deepcopy(after)
        wrong[('keywords', 'xmp')]['container'] = 'Seq'
        self.assertEqual([p['code'] for p in proofs.readback(plan, before, wrong, '$.items[0]')], ['READBACK_SHAPE_MISMATCH'])
        wrong = copy.deepcopy(after)
        wrong[('title', 'xmp')]['value']['x-default'] = 'U'
        found = proofs.readback(plan, before, wrong, '$.items[0]')
        self.assertEqual((found[0]['code'], found[0]['location']), ('READBACK_MISMATCH', '$.items[0].fields.title.xmp'))
        wrong = copy.deepcopy(after)
        wrong[('keywords', 'xmp')]['value'] = ['b', 'a']
        self.assertEqual([p['code'] for p in proofs.readback(plan, before, wrong, '$.items[0]')], ['READBACK_MISMATCH'])


class Planning(Base):
    def test_closed_envelope_and_media_narrowing(self):
        item = [{'id': 'a', 'path': '/x/a.jpg'}]
        ok = adaptor.plan(doc('editMetadata', item, edits={'title': {'set': 'T'}}))
        self.assertEqual((ok['version'], ok['catalogue']['version'], ok['writes']['version']), ('schemaxis.exiftool.edit.plan/1', 'schemaxis.exiftool.fields/2', 'schemaxis.exiftool.writes/1'))
        self.assertEqual(ok['policies'], {'iptc': 'ifPresent', 'otherLanguages': 'keep', 'exifEncoding': 'utf8', 'companionLoss': 'removeCompanion'})
        self.fault(lambda: adaptor.plan({**doc('editMetadata', item, edits={'title': {'set': 'T'}}), 'categories': ['location']}), 'UNKNOWN_ARGUMENT', '$')
        self.fault(lambda: adaptor.plan({**doc('removeMetadata', item, categories=['location']), 'edits': {'title': {'set': 'T'}}}), 'UNKNOWN_ARGUMENT', '$')
        self.fault(lambda: adaptor.plan({**doc('editMetadata', item, edits={'title': {'set': 'T'}}), 'photos': item}), 'UNKNOWN_ARGUMENT')
        self.fault(lambda: adaptor.plan(doc('editMetadata', [{'id': 'a', 'path': '/x/a.jpg', 'sidecar': '/x/a.xmp'}], edits={'title': {'set': 'T'}})), 'WRITE_SIDECAR_UNSUPPORTED', '$.media.items[0].sidecar')
        self.fault(lambda: adaptor.plan(doc('editMetadata', [{'id': 'a', 'path': '/x/a.txt'}], edits={'title': {'set': 'T'}})), 'INVALID_PHOTO_SOURCE')      # E5: .png and the other container suffixes are written too
        self.fault(lambda: adaptor.plan({**doc('editMetadata', item, edits={'title': {'set': 'T'}}), 'media': {'folder': {'path': '/x', 'extensions': ['.jpg', '.xmp']}}}), 'INVALID_ARGUMENT', '$.media.folder.extensions')
        folder = adaptor.plan({**doc('removeMetadata', item, categories=['location']), 'media': {'folder': {'path': '/x'}}})
        self.assertEqual((folder['media']['folder']['extensions'], folder['media']['folder']['sidecars']), (['.jpg', '.jpeg'], 'none'))
        self.fault(lambda: adaptor.plan(doc('removeMetadata', item, categories=['location', 'banana'])), 'INVALID_ARGUMENT')
        self.fault(lambda: adaptor.plan(doc('editMetadata', item, edits={})), 'EDIT_INVALID', '$.edits')
        per = adaptor.plan(doc('editMetadata', item + [{'id': 'b', 'path': '/x/b.jpg'}], edits={'title': {'set': 'T'}}, itemEdits=[{'item': 'b', 'edits': {'rating': {'set': 5}}}]))
        self.assertEqual(editing.item_edits_of(per, 'b'), {'title': {'set': {'text': 'T', 'languages': []}}, 'rating': {'set': 5}})
        self.assertEqual(editing.item_edits_of(per, 'a'), {'title': {'set': {'text': 'T', 'languages': []}}})
        self.fault(lambda: adaptor.plan(doc('editMetadata', item, edits={'title': {'set': 'T'}}, itemEdits=[{'item': 'zz', 'edits': {'rating': {'set': 5}}}])), 'UNKNOWN_ITEM', '$.itemEdits[0].item')
        self.fault(lambda: adaptor.plan({**doc('editMetadata', item, edits={'title': {'set': 'T'}}, itemEdits=[{'item': 'a', 'edits': {'rating': {'set': 5}}}]), 'media': {'folder': {'path': '/x'}}}), 'ITEM_EDITS_NEED_ITEMS')
        text = json.dumps(adaptor.schema()).lower()
        for banned in ('tagname', '"tags"', 'perl', 'expression', '-api'):
            self.assertNotIn(banned, text)

    def test_removal_categories_are_exclusive_where_declared_and_plans_are_deterministic(self):
        a = adaptor.plan(doc('removeMetadata', [{'id': 'a', 'path': '/x/a.jpg'}], categories=['rights', 'location']))
        self.assertEqual(a['categories'], ['location', 'rights'])
        self.assertEqual(adaptor.plan_hash(a), adaptor.plan_hash(adaptor.plan(doc('removeMetadata', [{'id': 'a', 'path': '/x/a.jpg'}], categories=['location', 'rights']))))


def executable():
    path = os.environ.get('SCHEMAXIS_EXIFTOOL')
    return path if path and Path(path).is_file() else None


class Native(Base):
    """Real ExifTool 13.55: genuine writes, three proofs recomputed by verify, exact semantic mutants and the public workflow chain."""
    EXPECT_TITLE = 'Ridge at dawn'

    @classmethod
    def setUpClass(cls):
        cls.exe = executable()
        if cls.exe is None:
            raise unittest.SkipTest('real ExifTool 13.55 is not configured through SCHEMAXIS_EXIFTOOL; tools/qualify_exiftool_write.py runs the same flows')
        cls.tmp = Path(tempfile.mkdtemp(prefix='schemaxis-exiftool-write-test-')).resolve()
        cls.addClassCleanup(shutil.rmtree, cls.tmp, ignore_errors=True)       # only the directory this class created
        cls.media = cls.tmp / 'media'
        cls.media.mkdir()
        for name, data in FILES.items():
            (cls.media / name).write_bytes(data)
        cls.main = cls.edit(cls.tmp / 'main', ['edit-rich.jpg', 'edit-trailer.jpg', 'edit-rich-mm.jpg'],
                            {'title': {'set': {'text': cls.EXPECT_TITLE, 'languages': [{'language': 'fr', 'text': 'Crête à l\u2019aube'}]}}, 'description': {'set': 'Two hikers.\nSecond line.'},
                             'keywords': {'set': ['alpine', 'Grand Teton']}, 'creator': {'set': ['Ana Núñez', '李伟', 'Smith; Jones "Jr"']}, 'copyright': {'set': '© 2026 Ana Núñez'},
                             'rightsUrl': {'set': 'https://example.org/licence'}, 'rating': {'set': 4}, 'locationCity': {'set': 'Zürich'}})

    @classmethod
    def edit(cls, target, names, edit_map, **extra):
        items = [{'id': Path(n).stem.replace('-', '_'), 'path': str(cls.media / n)} for n in names]
        return editing.run(doc('editMetadata', items, edits=edit_map, **extra), target, executable=cls.exe, timeout=300)

    def ids(self, *names): return [Path(n).stem.replace('-', '_') for n in names]

    def read(self, path):
        located = containers.locate(Path(path).read_bytes())
        return records.build(located, list(catalogue.fields(catalogue.VERSION_MWG)), None, catalogue.VERSION_MWG)[1]

    def test_edit_values_read_back_from_the_published_jpegs_by_the_standard_library_readers(self):
        self.assertEqual((self.main['written'], self.main['refused'], self.main['setStatus']), (2, 1, 'partial'))
        for name in ('edit_rich', 'edit_rich_mm'):
            fields = self.read(self.tmp / 'main' / 'photos' / (name + '.jpg'))
            expected = {'title': self.EXPECT_TITLE, 'description': 'Two hikers.\nSecond line.', 'keywords': ('alpine', 'Grand Teton'), 'creator': ('Ana Núñez', '李伟', 'Smith; Jones "Jr"'),
                        'copyright': '© 2026 Ana Núñez', 'rightsUrl': 'https://example.org/licence', 'rating': 4, 'locationCity': 'Zürich'}
            for field, value in expected.items():
                self.assertEqual((fields[field]['state'], fields[field]['canonical']), ('present', value), (name, field))
                self.assertIn(fields[field]['reconciliation'], ('consistent', 'single-source'), (name, field))
            self.assertEqual(fields['orientation']['canonical'], 6 if name == 'edit_rich' else 8)    # rendering metadata kept
        out = (self.tmp / 'main' / 'photos' / 'edit_rich.jpg').read_bytes()
        self.assertIn('Crête à l\u2019aube'.encode(), out)
        self.assertNotIn(b'Old title</rdf:li>', out)

    def test_encoded_image_and_rendering_segments_are_byte_identical_to_the_captures(self):
        for name in ('edit_rich', 'edit_rich_mm'):
            before = (self.tmp / 'main' / 'captured' / (name + '.jpg')).read_bytes()
            after = (self.tmp / 'main' / 'photos' / (name + '.jpg')).read_bytes()
            self.assertEqual(after[jpegwrite.walk(after)['firstScan']:], before[jpegwrite.walk(before)['firstScan']:])
            for needle in (b'ICC_PROFILE\0\x01\x02', b'Adobe\0'):
                self.assertEqual(before[before.index(needle):before.index(needle) + 30], after[after.index(needle):after.index(needle) + 30])
        self.assertEqual((self.media / 'edit-rich.jpg').read_bytes(), FILES['edit-rich.jpg'])         # the original is untouched

    def test_stable_artifact_slots_never_shift_a_refused_item(self):
        receipt = json.loads((self.tmp / 'main' / 'verification.json').read_text())
        kinds = [(a['kind'], a['identity'].get('item') if 'identity' in a else None) for a in receipt['artifacts']]
        self.assertEqual(kinds[:3], [('image', 'edit_rich'), ('text', 'edit_trailer'), ('image', 'edit_rich_mm')])
        self.assertEqual([k for k, _ in kinds[3:]], ['text', 'text', 'text'])
        outcome = json.loads((self.tmp / 'main' / 'outcomes' / 'edit_trailer.json').read_text())
        self.assertEqual((outcome['status'], outcome['image'], outcome['fault']['code']), ('refused', False, 'WRITE_TRAILER_UNSUPPORTED'))
        self.assertEqual(receipt['artifacts'][1]['file'].rsplit('/', 1)[-1], 'edit_trailer.json')

    def mutate(self, name, mutate):
        target = self.tmp / ('mutant-' + name)
        shutil.copytree(self.tmp / 'main', target, symlinks=True)
        mutate(target)
        with self.assertRaises(SchemaxisError) as caught:
            editing.verify(target, executable=self.exe)
        fault = caught.exception.fault
        cause = fault.observed.get('cause', {})
        return cause.get('code', fault.code), fault.location

    def tamper(self, relative, replace):
        def go(directory):
            path = directory / relative
            data = path.read_bytes()
            path.write_bytes(replace(data))
        return go

    def test_semantic_mutants_fail_verify_with_one_exact_code_and_location(self):
        photos = 'photos/edit_rich.jpg'
        xmp_title = lambda d: d.replace(b'>Ridge at dawn</rdf:li>', b'>Ridge at dusk</rdf:li>', 1)
        self.assertEqual(self.mutate('value', self.tamper(photos, xmp_title)), ('READBACK_MISMATCH', '$.items[0].fields.title.xmp'))
        self.assertEqual(self.mutate('kind', self.tamper(photos, lambda d: d.replace(b'rdf:Bag', b'rdf:Seq'))), ('READBACK_SHAPE_MISMATCH', '$.items[0].fields.keywords.xmp'))
        self.assertEqual(self.mutate('toolkit', self.tamper(photos, lambda d: d.replace(b"x:xmptk='Image::ExifTool 13.55'", b"x:xmptk='Image::ExifTool 13.56'"))), ('NATIVE_UNEXPLAINED_CHANGE', '$.items[0].native'))
        self.assertEqual(self.mutate('software', self.tamper(photos, lambda d: d.replace(b'Synthetic fixture generator', b'Synthetic fixture generatoR'))), ('EXIF_NONTARGET_CHANGED', '$.items[0].exif'))      # found by the independent Exif walker, before any native diff

        def scan(d):
            index = d.rindex(b'\xff\xda') + 14
            return d[:index] + bytes([d[index] ^ 0x40]) + d[index + 1:]
        self.assertEqual(self.mutate('scan', self.tamper(photos, scan)), ('IMAGE_DATA_CHANGED', '$.items[0].image'))
        self.assertEqual(self.mutate('icc', self.tamper(photos, lambda d: d.replace(b'mntr', b'mntR', 1))), ('RENDERING_SEGMENT_CHANGED', '$.items[0].image'))
        self.assertEqual(self.mutate('adobe', self.tamper(photos, lambda d: d.replace(b'Adobe\0\x64', b'Adobe\0\x65', 1))), ('RENDERING_SEGMENT_CHANGED', '$.items[0].image'))
        self.assertEqual(self.mutate('comment', self.tamper(photos, lambda d: d.replace(b'a synthetic comment', b'a synthetic commenT'))), ('SEGMENT_CHANGED', '$.items[0].image'))

    def test_capture_overwrite_aliases_and_publication_mutants(self):
        code, location = self.mutate('capture', self.tamper('captured/edit_rich.jpg', lambda d: d + b'x'))
        self.assertEqual((code, location), ('VERIFICATION_FAILED', 'captured/edit_rich.jpg'))

        def hard_link(directory):
            (directory / 'photos/edit_rich.jpg').unlink()
            os.link(directory / 'captured/edit_rich.jpg', directory / 'photos/edit_rich.jpg')
        code, location = self.mutate('hardlink', hard_link)
        self.assertIn(code, ('READBACK_MISMATCH', 'OUTPUT_ALIASES_CAPTURE'))

        def symlink(directory):
            (directory / 'photos/edit_rich.jpg').unlink()
            os.symlink(directory / 'captured/edit_rich.jpg', directory / 'photos/edit_rich.jpg')
        self.assertEqual(self.mutate('symlink', symlink)[0], 'VERIFICATION_FAILED')
        for name in ('edit-report.json', 'manifest.json', 'edit-plan.json'):
            code, location = self.mutate('doc-' + name, self.tamper(name, lambda d: d.replace(b'"written"', b'"writteN"', 1)))
            self.assertEqual((code, location), ('VERIFICATION_FAILED', name))

    def test_the_main_run_verifies_again_and_a_plan_change_fails_closed(self):
        self.assertTrue(editing.verify(self.tmp / 'main', executable=self.exe)['verified'])
        target = self.tmp / 'mutant-authored'
        shutil.copytree(self.tmp / 'main', target, symlinks=True)
        authored = json.loads((target / 'authored.json').read_text())
        authored['edits']['rating']['set'] = 3
        (target / 'authored.json').write_text(json.dumps(authored))
        with self.assertRaises(SchemaxisError) as caught:
            editing.verify(target, executable=self.exe)
        self.assertEqual(caught.exception.fault.code, 'VERIFICATION_FAILED')

    def test_progressive_restart_and_multiscan_files_keep_every_scan_byte_identical(self):
        names = ['edit-progressive.jpg', 'edit-restart.jpg', 'edit-multiscan.jpg']
        result = self.edit(self.tmp / 'scans', names, {'title': {'set': 'Scan title'}, 'creator': {'set': ['Ana']}})
        self.assertEqual((result['written'], result['failed'], result['refused']), (3, 0, 0))
        for name in self.ids(*names):
            before = (self.tmp / 'scans' / 'captured' / (name + '.jpg')).read_bytes()
            after = (self.tmp / 'scans' / 'photos' / (name + '.jpg')).read_bytes()
            self.assertEqual(after[after.index(b'\xff\xda'):], before[before.index(b'\xff\xda'):], name)
        self.assertEqual(containers.locate((self.tmp / 'scans' / 'photos' / 'edit_progressive.jpg').read_bytes())['scans'], 10)

    def test_legacy_iptc_text_is_never_reinterpreted(self):
        result = self.edit(self.tmp / 'legacy', ['edit-legacy-iptc.jpg', 'edit-ascii-iptc.jpg'], {'creator': {'set': ['Ana Núñez']}})
        self.assertEqual((result['written'], result['refused']), (2, 0))
        legacy = (self.tmp / 'legacy' / 'photos' / 'edit_legacy_iptc.jpg').read_bytes()
        self.assertIn(b'Caf\xe9', legacy)                      # untouched Latin-1 title bytes
        self.assertNotIn(b'\x1b%G', legacy)                    # no character set was declared over them
        by_line = containers.locate(legacy)['iptc'][0]
        self.assertNotIn('李', by_line.decode('latin-1'))
        ascii_file = (self.tmp / 'legacy' / 'photos' / 'edit_ascii_iptc.jpg').read_bytes()
        self.assertIn(b'\x1b%G', ascii_file)                   # every untouched dataset was ASCII, so UTF-8 is declared
        self.assertIn('Ana Núñez'.encode(), ascii_file)
        report = json.loads((self.tmp / 'legacy' / 'edit-report.json').read_text())
        self.assertEqual([x['reason'] for x in report['items'][0]['losses']], ['iptcCharsetUnknown'])

    def test_other_languages_keep_and_remove_and_exif_is_never_created(self):
        kept = self.edit(self.tmp / 'lang-keep', ['edit-languages.jpg', 'edit-jfif-only.jpg'], {'title': {'set': 'Neuer Titel'}})
        self.assertEqual(kept['written'], 2)
        out = (self.tmp / 'lang-keep' / 'photos' / 'edit_languages.jpg').read_bytes()
        self.assertIn('Alter Titel'.encode(), out)
        jfif = (self.tmp / 'lang-keep' / 'photos' / 'edit_jfif_only.jpg').read_bytes()
        self.assertNotIn(b'Exif\0\0', jfif)
        removed = self.edit(self.tmp / 'lang-remove', ['edit-languages.jpg'], {'title': {'set': 'Neuer Titel'}}, policies={'otherLanguages': 'remove'})
        self.assertEqual(removed['written'], 1)
        self.assertNotIn('Alter Titel'.encode(), (self.tmp / 'lang-remove' / 'photos' / 'edit_languages.jpg').read_bytes())

    def test_removal_proves_absence_independently_and_natively_and_states_its_limits(self):
        names = ['edit-rich.jpg', 'edit-maker.jpg', 'edit-trailer.jpg']
        items = [{'id': Path(n).stem.replace('-', '_'), 'path': str(self.media / n)} for n in names]
        result = editing.run(doc('removeMetadata', items, categories=['location', 'thumbnails', 'descriptive']), self.tmp / 'remove', executable=self.exe, timeout=300)
        self.assertEqual((result['written'], result['refused']), (2, 1))
        out = (self.tmp / 'remove' / 'photos' / 'edit_rich.jpg').read_bytes()
        located = containers.locate(out)
        self.assertNotIn(b'Shown City', out)
        self.assertNotIn(b'a synthetic comment', out)
        fields = records.build(located, ['gpsLatitude', 'locationCity', 'title', 'description', 'keywords', 'orientation', 'cameraMake'], None, catalogue.VERSION_MWG)[1]
        self.assertEqual([fields[f]['state'] for f in ('gpsLatitude', 'locationCity', 'title', 'description', 'keywords')], ['absent'] * 5)
        self.assertEqual((fields['orientation']['canonical'], fields['cameraMake']['canonical']), (6, 'Northfield'))       # rendering and device kept: not requested
        residual = json.loads((self.tmp / 'remove' / 'residual.json').read_text())
        self.assertTrue(any('pixel content' in x for x in residual['limits']))
        self.assertNotIn('GPS', residual['items'][0]['nativeResidual'])
        self.assertEqual(json.loads((self.tmp / 'remove' / 'removal-report.json').read_text())['items'][1]['status'], 'written')
        device = editing.run(doc('removeMetadata', items[1:2] + [items[0]], categories=['deviceIdentity']), self.tmp / 'device', executable=self.exe, timeout=300)
        self.assertEqual((device['written'], device['refused']), (1, 1))
        refused = json.loads((self.tmp / 'device' / 'outcomes' / 'edit_maker.json').read_text())
        self.assertEqual((refused['status'], refused['image'], refused['fault']['code']), ('refused', False, 'MAKERNOTE_UNDELETABLE'))

        def restore(directory):
            (directory / 'photos/edit_rich.jpg').write_bytes((directory / 'captured/edit_rich.jpg').read_bytes())
        target = self.tmp / 'remove-mutant'
        shutil.copytree(self.tmp / 'remove', target, symlinks=True)
        restore(target)
        with self.assertRaises(SchemaxisError) as caught:
            editing.verify(target, executable=self.exe)
        self.assertEqual(caught.exception.fault.observed['cause']['code'], 'REMOVAL_RESIDUAL')

    def test_a_native_warning_fails_only_that_item_and_keeps_the_others(self):
        """C28: a real ExifTool warning on stderr (rc 0) is a fault. The bad assignment is injected for the test only; the planner never produces one."""
        original = edits.assignments

        def inject(plan):
            args = original(plan)
            return args + ['-XMP-xmp:Rating=not-a-number'] if any(f['field'] == 'title' for f in plan['fields'].values()) and plan['fields']['title']['value']['text'] == 'Injected' else args
        names = ['edit-rich.jpg', 'edit-rich-mm.jpg']
        edits.assignments = inject
        try:
            items = [{'id': 'bad', 'path': str(self.media / names[0])}, {'id': 'good', 'path': str(self.media / names[1])}]
            first = editing.run(doc('editMetadata', items[:1] + items[1:], edits={'title': {'set': 'Injected'}}, itemEdits=[{'item': 'good', 'edits': {'title': {'set': 'Fine title'}}}]), self.tmp / 'warning', executable=self.exe, timeout=300)
        finally:
            edits.assignments = original
        self.assertEqual((first['written'], first['failed'], first['setStatus']), (1, 1, 'partial'))
        outcome = json.loads((self.tmp / 'warning' / 'outcomes' / 'bad.json').read_text())
        self.assertEqual((outcome['status'], outcome['image'], outcome['fault']['code']), ('failed', False, 'NATIVE_WRITE_WARNING'))
        self.assertTrue((self.tmp / 'warning' / 'rejected' / 'bad.jpg').is_file())            # quarantined, never published as an artifact
        self.assertFalse((self.tmp / 'warning' / 'photos' / 'bad.jpg').exists())
        receipt = json.loads((self.tmp / 'warning' / 'verification.json').read_text())
        self.assertEqual([(a['kind'], a.get('identity', {}).get('item')) for a in receipt['artifacts'][:2]], [('text', 'bad'), ('image', 'good')])
        with self.assertRaises(SchemaxisError) as caught:      # the planner would never have produced the injected assignment, so a clean verify refuses the retained plan
            editing.verify(self.tmp / 'warning', executable=self.exe)
        self.assertEqual(caught.exception.fault.code, 'VERIFICATION_FAILED')

    def test_every_item_failing_fails_the_run_and_publishes_no_image(self):
        items = [{'id': 'trail', 'path': str(self.media / 'edit-trailer.jpg')}]
        with self.assertRaises(SchemaxisError) as caught:
            editing.run(doc('editMetadata', items, edits={'title': {'set': 'T'}}), self.tmp / 'allfail', executable=self.exe, timeout=300)
        self.assertEqual(caught.exception.fault.code, 'NO_USABLE_ITEMS')
        self.assertEqual(json.loads((self.tmp / 'allfail' / 'result.json').read_text())['status'], 'failed')
        self.assertFalse((self.tmp / 'allfail' / 'photos').exists())
        self.assertFalse((self.tmp / 'allfail' / 'verification.json').exists())
        with self.assertRaises(SchemaxisError):
            editing.run(doc('editMetadata', items, edits={'title': {'set': 'T'}}), self.tmp / 'allfail', executable=self.exe, timeout=300)    # C27: a used output directory is refused

    def test_a_workflow_chain_binds_exact_slots_and_never_the_wrong_photo(self):
        from schemaxis import workflow
        old = os.environ.get('SCHEMAXIS_EXIFTOOL')
        os.environ['SCHEMAXIS_EXIFTOOL'] = self.exe
        try:
            edit = doc('editMetadata', [{'id': 'ridge', 'path': str(self.media / 'edit-rich.jpg')}, {'id': 'trail', 'path': str(self.media / 'edit-trailer.jpg')}, {'id': 'camp', 'path': str(self.media / 'edit-rich-mm.jpg')}],
                       edits={'title': {'set': 'Chained title'}, 'creator': {'set': ['Ana Núñez', 'Li Wei']}})

            def chain(name, index):
                check = {'version': 'schemaxis.exiftool/1', 'operation': 'inspectMetadata', 'creatorInterpretation': 'mwg', 'profiles': ['description', 'rights'], 'media': {'items': [{'id': 'seen', 'path': {'$artifact': 'tidy', 'index': index}}]}}
                return workflow.execute({'version': 'schemaxis.workflow/1', 'operations': [{'id': 'tidy', 'document': edit}, {'id': 'check', 'document': check}]}, self.tmp / name, timeout=300)
            self.assertEqual(chain('chain-0', 0)['status'], 'succeeded')
            csv = next((self.tmp / 'chain-0').rglob('profile-rights.csv')).read_text()
            self.assertIn('Ana Núñez', csv)
            # the refused item's slot is an outcome document, never an image. Since E3 the route also accepts text artifacts (a published plan binds to `plan`), so the
            # binding is no longer rejected by artifact kind; the consumer refuses the outcome path itself, still never reading another photo.
            self.fault(lambda: chain('chain-1', 1), 'INVALID_PHOTO_SOURCE', '$.media.items[0].path')
            self.assertEqual(chain('chain-2', 2)['status'], 'succeeded')
            self.fault(lambda: chain('chain-9', 99), 'INVALID_SELECTION')
        finally:
            if old is None:
                os.environ.pop('SCHEMAXIS_EXIFTOOL', None)
            else:
                os.environ['SCHEMAXIS_EXIFTOOL'] = old


if __name__ == '__main__':
    unittest.main()
