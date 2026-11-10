"""Completion tests of the ExifTool write family: rendering-preserving minimise, the XMP qualifier refusal, the independent non-target Exif proof
and the IPTC character-set scope.

Host tests need no native process. Native tests need a real ExifTool 13.55 through SCHEMAXIS_EXIFTOOL and are skipped otherwise. Every expected
value is a literal written here, never taken from ExifTool or from the code under test.
"""
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(ROOT / 'tools'))
sys.path.insert(0, str(ROOT / 'tests/unit'))

import author_exiftool_fixtures as author  # noqa: E402
from schemaxis import publication_metadata  # noqa: E402
from schemaxis.adaptors.exiftool import adaptor, containers, edits, editing, jpegwrite, proofs, records, removal, writes, xmp as xmp_reader  # noqa: E402
from schemaxis.artifacts import atomic_json  # noqa: E402
from schemaxis.core.faults import SchemaxisError  # noqa: E402
from schemaxis.dispatch import allocation  # noqa: E402
from test_exiftool_write import Base, FILES, doc, executable  # noqa: E402

ORDER = 'II'


def author_sha(data):
    import hashlib
    return hashlib.sha256(data).hexdigest()


def variant(seed, **kw):
    return author.edit_fixture(seed=seed, **kw)


TITLE = author.alt('dc:title', [('x-default', 'Old title')])
EXTRA = {
    'min-colorspace.jpg': variant(401, exif_entries=[author.short_entry(ORDER, 0xA001, 1)], ifd0_entries=[author.short_entry(ORDER, 0x0213, 2)]),
    'min-gamma.jpg': variant(402, exif_entries=[author.rational_entry(ORDER, 0xA500, (22, 10))]),
    'min-xmp-conflict.jpg': variant(403, xmp_properties=TITLE + '<tiff:Orientation>3</tiff:Orientation>'),
    'min-xmp-agrees.jpg': variant(404, xmp_properties=TITLE + '<tiff:Orientation>6</tiff:Orientation>'),
    'min-orientation-nine.jpg': variant(405, orientation=9),
    'qual-bag.jpg': variant(406, xmp_properties=TITLE + '<dc:subject><rdf:Bag><rdf:li xml:lang="fr">alpin</rdf:li><rdf:li>dawn</rdf:li></rdf:Bag></dc:subject>', iptc=False),
    'qual-struct.jpg': variant(407, xmp_properties=TITLE + '<dc:creator><rdf:Seq><rdf:li><rdf:Description><rdf:value>Ana</rdf:value><xmp:Label>qualified</xmp:Label></rdf:Description></rdf:li></rdf:Seq></dc:creator>', iptc=False),
    'legacy-record3.jpg': variant(408, iptc_utf8=False, iptc_sets=[(2, 80, 'Old Artist'), (3, 10, b'caf\xe9')]),
    'legacy-record7.jpg': variant(409, iptc_utf8=False, iptc_sets=[(2, 80, 'Old Artist'), (7, 10, b'caf\xe9')]),
    'legacy-envelope.jpg': variant(410, iptc_utf8=False, iptc_sets=[(1, 5, b'caf\xe9'), (2, 80, 'Old Artist')]),
}
ALL = {**FILES, **EXTRA}


def descendants(pid):
    found = []
    for task in Path('/proc/%d/task' % pid).iterdir():
        try:
            children = [int(x) for x in (task / 'children').read_text().split()]
        except OSError:
            continue
        for child in children:
            found += [child, *descendants(child)]
    return found


def group_alive(pgid):
    try:
        os.killpg(pgid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def pid_alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    try:                      # a reaped-but-unwaited zombie is not alive
        return Path('/proc/%d/stat' % pid).read_text().rsplit(')', 1)[1].split()[0] != 'Z'
    except OSError:
        return False


def refresh(directory, old):
    """Refresh every ordinary mutable binding of a copied run after a tamper (stage input digests, receipt evidence and artifact records, publication metadata) and
    require ``publication_metadata.verify`` to pass, so that only a semantic fault can remain."""
    directory = Path(directory)
    for path in sorted(directory.glob('*-submission.json')):            # the recorded launcher paths name the run directory
        path.write_text(path.read_text().replace(str(old), str(directory)))
    for path in sorted(directory.glob('*-inputs.json')):
        data = json.loads(path.read_text())
        atomic_json(path, {'files': {n: editing.digest_of(directory, editing.stage_path_of(directory, n) if n.startswith('stage/') else n, editing.limit_of(n)) for n in data['files']}})
    receipt = json.loads((directory / 'verification.json').read_text())
    receipt['evidence'] = {n: editing.digest_of(directory, n, editing.limit_of(n)) for n in receipt['evidence']}
    for entry in receipt['artifacts']:
        entry['file'] = str(directory / Path(entry['file']).relative_to(old))
        entry['sha256'] = editing.digest_of(directory, str(Path(entry['file']).relative_to(directory)), editing.limit_of(str(Path(entry['file']).relative_to(directory))))
        if entry['kind'] == 'image':
            entry['sha256'] = adaptor.sha(Path(entry['file']).read_bytes())
    atomic_json(directory / 'verification.json', receipt)
    publication_metadata.finalise(directory)
    assert publication_metadata.verify(directory)['verified'], 'publication metadata must verify after the refresh'


def thumbnail_of(data):
    return editing.thumbnail(containers.locate(data))


DC = '{http://purl.org/dc/elements/1.1/}'
RDF = '{http://www.w3.org/1999/02/22-rdf-syntax-ns#}'
XML_LANG = '{http://www.w3.org/XML/1998/namespace}lang'


def segments(data):
    """Independent marker scan (no adaptor code): ``([(marker, body)...], offset of the first scan header)``."""
    assert data[:2] == b'\xff\xd8'
    position, found = 2, []
    while data[position] == 0xFF and data[position + 1] != 0xDA:
        length = int.from_bytes(data[position + 2:position + 4], 'big')
        found.append((data[position + 1], data[position + 4:position + 2 + length]))
        position += 2 + length
    return found, position


def iim(data):
    """Every IPTC-IIM dataset ``(record, dataset, bytes)`` of the Photoshop resource 0x0404, read by a local parser."""
    found = []
    for marker, body in segments(data)[0]:
        if marker != 0xED or not body.startswith(b'Photoshop 3.0\0'):
            continue
        i = 14
        while i + 12 <= len(body) and body[i:i + 4] == b'8BIM':
            resource, j = int.from_bytes(body[i + 4:i + 6], 'big'), i + 6
            j += (1 + body[j]) + (1 + body[j]) % 2
            size = int.from_bytes(body[j:j + 4], 'big')
            payload, i = body[j + 4:j + 4 + size], j + 4 + size + size % 2
            if resource == 0x0404:
                k = 0
                while k < len(payload):
                    assert payload[k] == 0x1C and payload[k + 3] < 0x80, 'a standard dataset is expected'
                    length = int.from_bytes(payload[k + 3:k + 5], 'big')
                    found.append((payload[k + 1], payload[k + 2], payload[k + 5:k + 5 + length]))
                    k += 5 + length
    return found


def iim_values(data, record, dataset):
    return [value for r, d, value in iim(data) if (r, d) == (record, dataset)]


def iim_without(data, *skipped):
    """The IIM datasets minus the named ``(record, dataset)`` pairs and the two record-version datasets ExifTool adds (declared side effect S6)."""
    return [(r, d, v) for r, d, v in iim(data) if (r, d) not in skipped + ((1, 0), (2, 0))]


def xmp_property(data, namespace, name):
    """``(container, [(language or None, text)...])`` of one rdf:Alt/Bag/Seq property of the XMP packet, read with the standard XML parser."""
    import xml.etree.ElementTree as ET
    for marker, body in segments(data)[0]:
        if marker == 0xE1 and body.startswith(b'http://ns.adobe.com/xap/1.0/\0'):
            root = ET.fromstring(body[29:].decode('utf-8'))
            for node in root.iter('{%s}%s' % (namespace, name)):
                container = list(node)[0]
                return container.tag[len(RDF):], [(li.get(XML_LANG), li.text) for li in container]
    return None


def scan_tail(data):
    return data[segments(data)[1]:]


class Completion(Base):
    def item(self, name):
        data = ALL[name]
        located = containers.locate(data)
        return {'bytes_': data, 'walk': jpegwrite.walk(data), 'located': located, 'payloads': records.Payloads(located)}

    def minimise(self, name):
        return removal.plan_item(['minimise'], self.item(name), {'observations': []})

    def refusal(self, name, code):
        with self.assertRaises(edits.Refusal) as caught:
            self.minimise(name)
        self.assertEqual(caught.exception.code, code)
        return caught.exception


class Charset(Completion):
    def test_the_scope_is_what_exiftool_decodes_plus_the_envelope(self):
        scoped = [(1, 5), (2, 5), (2, 120), (3, 10), (6, 1)]
        unscoped = [(1, 90), (7, 10), (8, 10), (9, 10)]
        self.assertEqual([edits.charset_scoped(k) for k in scoped], [True] * 5)
        self.assertEqual([edits.charset_scoped(k) for k in unscoped], [False] * 4)

    def plan(self, name):
        item = self.item(name)
        return edits.plan_item({'creator': edits.normalise_edit('creator', {'set': ['Ana Núñez']}, '$.edits.creator')}, item['payloads'], edits.normalise_policies({}), False)

    def test_a_legacy_dataset_outside_record_two_stops_the_charset_assignment(self):
        for name in ('legacy-record3.jpg', 'legacy-envelope.jpg'):
            plan = self.plan(name)
            self.assertFalse(plan['iptc']['assignCharset'], name)
            self.assertEqual([x['reason'] for x in plan['fields']['creator']['losses']], ['iptcCharsetUnknown'], name)
        beyond = self.plan('legacy-record7.jpg')                       # ExifTool never decodes record 7 through 1:90
        self.assertTrue(beyond['iptc']['assignCharset'])
        self.assertEqual(beyond['fields']['creator']['losses'], [])

    def test_the_readback_proof_refuses_a_charset_change_over_an_untouched_record_three_dataset(self):
        before = self.item('legacy-record3.jpg')
        plan = {'fields': {'creator': {}}, 'iptc': {'changed': True, 'assignCharset': True}}
        after = before['bytes_'].replace(b'Old Artist', b'New Artist')
        header = author.iptc_dataset(1, 90, b'\x1b%G')
        # the output declares UTF-8 while the untouched record-3 text keeps its single high byte
        walk = before['walk']
        iim = next(s for s in walk['pre'] if s['role'] == 'iptc')
        tampered = author.iptc_app13([(2, 80, 'Old Artist'), (3, 10, b'caf\xe9')], True)
        segment = author.segment(0xED, tampered)
        original = author.segment(0xED, iim['body'])
        data = before['bytes_'].replace(original, segment)
        located = containers.locate(data)
        problems = proofs.iptc_untouched(plan, before['payloads'], records.Payloads(located), '$.items[0]')
        self.assertEqual([p['code'] for p in problems], ['IPTC_CHARSET_REINTERPRETED'])
        self.assertEqual(problems[0]['datasets'], ['3:10'])
        self.assertTrue(header and after)


class Qualifiers(Completion):
    def test_the_reader_counts_what_a_rewrite_would_drop(self):
        def packet(body):
            return author.xmp_packet(body)
        bag_lang = packet('<dc:subject><rdf:Bag><rdf:li xml:lang="fr">alpin</rdf:li></rdf:Bag></dc:subject>')
        alt_lang = packet(author.alt('dc:title', [('x-default', 'a'), ('fr', 'b')]))
        plain = packet(author.bag('dc:subject', ['a', 'b']))
        struct = packet('<dc:creator><rdf:Seq><rdf:li><rdf:Description><rdf:value>Ana</rdf:value><xmp:Label>q</xmp:Label></rdf:Description></rdf:li></rdf:Seq></dc:creator>')
        self.assertEqual(xmp_reader.qualifiers(bag_lang, {'dc:subject'}), {'dc:subject': 1})
        self.assertEqual(xmp_reader.qualifiers(alt_lang, {'dc:title'}), {})           # xml:lang is the identity of an alternative, not a qualifier
        self.assertEqual(xmp_reader.qualifiers(plain, {'dc:subject'}), {})
        self.assertEqual(xmp_reader.qualifiers(struct, {'dc:creator'}), {'dc:creator': 1})
        self.assertEqual(xmp_reader.qualifiers(bag_lang, {'dc:creator'}), {})         # only the wanted properties are inspected


class ExifNonTarget(Completion):
    def test_a_changed_untargeted_entry_and_a_changed_maker_note_are_named(self):
        before = self.item('edit-maker.jpg')
        changed = before['bytes_'].replace(b'Synthetic fixture generator', b'Synthetic fixture generatoR')
        out = records.Payloads(containers.locate(changed))
        found = proofs.exif_nontarget(before['payloads'], out, set(), set(), '$.items[0]')
        self.assertEqual([(p['code'], p['entry'], p['location']) for p in found], [('EXIF_NONTARGET_CHANGED', 'IFD0:0x0131', '$.items[0].exif')])
        note = before['bytes_'].replace(b'MAKERNOTE-OPAQUE-0123456789', b'MAKERNOTE-OPAQUE-012345678X')
        out = records.Payloads(containers.locate(note))
        found = proofs.exif_nontarget(before['payloads'], out, set(), set(), '$.items[0]')
        self.assertEqual([(p['code'], p['entry']) for p in found], [('MAKERNOTE_CHANGED', 'ExifIFD:0x927C')])
        tiffs, effects = (before['located']['exif'][0], containers.locate(note)['exif'][0]), []
        found = proofs.exif_nontarget(before['payloads'], out, set(), set(), '$.items[0]', tiffs, effects)       # an opaque note is not a plain IFD: a changed byte can never be proved a relocation
        self.assertEqual(([(p['code'], p['entry']) for p in found], effects), ([('MAKERNOTE_CHANGED', 'ExifIFD:0x927C')], []))
        self.assertEqual(proofs.exif_nontarget(before['payloads'], out, {('ExifIFD', 0x927C)}, set(), '$.items[0]'), [])

    def test_a_named_target_a_deleted_ifd_and_the_moving_pointers_are_not_faults(self):
        before = self.item('edit-rich.jpg')
        self.assertEqual(proofs.exif_nontarget(before['payloads'], before['payloads'], set(), set(), '$'), [])
        gone = records.Payloads(containers.locate(before['bytes_'].replace(b'Old Artist', b'New Artist')))
        self.assertEqual(len(proofs.exif_nontarget(before['payloads'], gone, set(), set(), '$')), 1)
        self.assertEqual(proofs.exif_nontarget(before['payloads'], gone, {('IFD0', 0x013B)}, set(), '$'), [])


def canon_tiff(artist=b'Old Artist\0', tail=b'SLACKSLK', blob=b'UNKNOWNBLOB1', interop=None, count=2):
    """A little-endian TIFF payload whose ExifIFD carries a Canon-layout maker note (one plain IFD, offsets relative to the TIFF header) and, optionally, an Interop IFD.
    Every length is fixed before the offsets are written, so a longer artist moves the note and shifts its inner value offsets by one delta."""
    import struct as st

    def table(entries, base):
        head, data, where = st.pack('<H', len(entries)), b'', base + 2 + 12 * len(entries) + 4
        for tag, kind, number, payload in entries:
            if len(payload) <= 4:
                head += st.pack('<HHI', tag, kind, number) + payload.ljust(4, b'\0')
            else:
                head += st.pack('<HHII', tag, kind, number, where + len(data))
                data += payload + (b'\0' if len(payload) % 2 else b'')
        return head + st.pack('<I', 0) + data

    def layout(exif_at, interop_at, note_at):
        ifd0 = table([(0x010F, 2, 6, b'Canon\0'), (0x013B, 2, len(artist), artist), (0x8769, 4, 1, st.pack('<I', exif_at))], 8)
        rows = [(0x927C, 7, 0, b'')] if False else []
        note_entries = [(0x0006, 2, 16, b'Canon EOS SYNTH\0'), (0x00F0, 7, 12, blob)][:count]
        note = table(note_entries, note_at) + tail
        exif_rows = [(0x927C, 7, len(note), st.pack('<I', note_at))] + ([(0xA005, 4, 1, st.pack('<I', interop_at))] if interop else [])
        exif = st.pack('<H', len(exif_rows)) + b''.join(st.pack('<HHI', t, k, n) + v for t, k, n, v in exif_rows) + st.pack('<I', 0)
        inter = table([(0x0001, 2, 4, b'R98\0')], interop_at) if interop else b''
        return ifd0, exif, inter, note
    ifd0, exif, inter, note = layout(0, 0, 0)
    exif_at = 8 + len(ifd0)
    interop_at = exif_at + len(exif)
    note_at = interop_at + len(inter)
    ifd0, exif, inter, note = layout(exif_at, interop_at, note_at)
    return b'II*\0' + st.pack('<I', 8) + ifd0 + exif + inter + note


class MakerNoteRelocation(Completion):
    FOOTER = b'II*\0\x08\x00\x00\x00'

    def check(self, before, after):
        return proofs.maker_note_check(before, after, '$.items[0]')

    def test_a_moved_note_with_every_value_equal_is_a_relocation_and_nothing_else(self):
        one, two = canon_tiff(), canon_tiff(artist=b'A much longer artist name\0')
        self.assertNotEqual(proofs.maker_note_of(one)[1], proofs.maker_note_of(two)[1])             # the note really moved
        self.assertNotEqual(proofs.maker_note_of(one)[2], proofs.maker_note_of(two)[2])             # and its inner offsets differ
        self.assertEqual(self.check(one, two), ([], None))
        self.assertEqual(self.check(one, one), ([], None))

    def test_unreferenced_bytes_that_changed_are_a_declared_side_effect_with_hashes_and_ranges(self):
        import hashlib
        one, two = canon_tiff(), canon_tiff(artist=b'A much longer artist name\0', tail=self.FOOTER)
        found, effect = self.check(one, two)
        self.assertEqual(found, [])
        self.assertEqual((effect['rule'], effect['entry'], effect['noteBytes']), ('S8-makerNoteRebuilt', 'ExifIFD:0x927C', [len(proofs.maker_note_of(one)[2])] * 2))
        self.assertEqual([x['sha256'] for x in effect['unreferencedBefore']], [hashlib.sha256(b'SLACKSLK').hexdigest()])
        self.assertEqual([x['sha256'] for x in effect['unreferencedAfter']], [hashlib.sha256(self.FOOTER).hexdigest()])
        self.assertEqual(effect['unreferencedBefore'][0]['range'][1] - effect['unreferencedBefore'][0]['range'][0], 8)

    def test_a_changed_referenced_value_or_entry_is_refused_and_never_a_side_effect(self):
        one = canon_tiff()
        for label, other in (('referenced value, same length', canon_tiff(blob=b'UNKNOWNBLOB2')), ('entry count', canon_tiff(count=1)), ('moved and referenced value changed', canon_tiff(artist=b'A much longer artist name\0', blob=b'UNKNOWNBLOB2'))):
            found, effect = self.check(one, other)
            self.assertEqual(([p['code'] for p in found], effect), (['MAKERNOTE_CHANGED'], None), label)
        found, _ = self.check(one, canon_tiff(blob=b'UNKNOWNBLOB2'))
        self.assertEqual(found[0]['tags'], ['0x00F0'])

    def test_a_note_that_is_not_a_plain_ifd_is_refused_when_it_changed(self):
        one = canon_tiff()
        note_at = proofs.maker_note_of(one)[1]
        damaged = one[:note_at] + b'\xff\xff' + one[note_at + 2:]                                    # an entry count beyond the budget: not a walkable layout
        found, effect = self.check(one, damaged)
        self.assertEqual(([p['code'] for p in found], effect), (['MAKERNOTE_CHANGED'], None))
        self.assertIn('plain IFD', found[0]['message'])

    def test_the_interop_ifd_is_compared_by_the_local_parser(self):
        one = canon_tiff(interop=True)
        self.assertEqual(proofs.interop_rows(one), [(0x0001, 2, 4, b'R98\0')])
        two = canon_tiff(interop=True).replace(b'R98\0', b'R03\0')
        before = records.Payloads({'container': 'jpeg', 'frame': None, 'notes': [], 'exif': [one], 'xmp': [], 'iptc': []})
        after = records.Payloads({'container': 'jpeg', 'frame': None, 'notes': [], 'exif': [two], 'xmp': [], 'iptc': []})
        found = proofs.exif_nontarget(before, after, set(), set(), '$', (one, two), [])
        self.assertEqual([(p['code'], p['entry']) for p in found], [('EXIF_NONTARGET_CHANGED', 'Interop')])
        self.assertEqual(proofs.exif_nontarget(before, before, set(), set(), '$', (one, one), []), [])


class EmptiedIptc(Completion):
    def test_a_fully_cleared_iptc_block_is_a_declared_side_effect_and_nothing_else_is(self):
        ctx = {'xmpWritten': False, 'assignCharset': False, 'iptcChanged': True, 'digest': False, 'afterIimMd5': None, 'thumbnailSame': True, 'iptcEmptied': True}
        for key, before in ((('IPTC', 'IPTC', 'ApplicationRecordVersion'), ['4']), (('IPTC', 'IPTC', 'EnvelopeRecordVersion'), ['4']), (('IPTC', 'IPTC', 'CodedCharacterSet'), ['\x1b%G']), (('Photoshop', 'Photoshop', 'IPTCDigest'), ['0' * 32])):
            self.assertEqual(proofs.side_effect(key, before, [], ctx), 'S6-iptcEmptied', key)
            self.assertIsNone(proofs.side_effect(key, before, [], {**ctx, 'iptcEmptied': False}), key)
        self.assertIsNone(proofs.side_effect(('IPTC', 'IPTC', 'ApplicationRecordVersion'), ['4'], ['5'], ctx))           # a changed value is never an emptied block
        self.assertIsNone(proofs.side_effect(('IPTC', 'IPTC', 'Keywords'), ['k'], [], ctx))                                 # a text dataset is a plan target, never a side effect
        rich, bare = self.item('edit-rich.jpg'), self.item('edit-no-iptc.jpg')
        self.assertTrue(proofs.iptc_emptied(rich['payloads'], bare['payloads']))
        self.assertFalse(proofs.iptc_emptied(rich['payloads'], rich['payloads']))
        self.assertFalse(proofs.iptc_emptied(bare['payloads'], bare['payloads']))


class MinimisePlan(Completion):
    def test_the_plan_is_a_closed_list_with_independently_read_rendering_values(self):
        plan = self.minimise('edit-rich.jpg')
        self.assertEqual(removal.assignments(plan), ['-EXIF:all=', '-XMP:all=', '-IPTC:all=', '-Photoshop:all=', '-File:Comment=', '-ExifByteOrder=Little-endian', '-IFD0:Orientation#=6'])
        self.assertNotIn('-all=', removal.assignments(plan))
        self.assertEqual((plan['minimise']['preserved'], plan['minimise']['keptSegments']), ({'Orientation': 6}, ['0xE0', '0xE2', '0xEE']))
        big = self.minimise('edit-rich-mm.jpg')
        self.assertEqual(removal.assignments(big)[-2:], ['-ExifByteOrder=Big-endian', '-IFD0:Orientation#=8'])
        both = self.minimise('min-colorspace.jpg')
        self.assertEqual(both['minimise']['preserved'], {'Orientation': 6, 'YCbCrPositioning': 2, 'ColorSpace': 1})
        self.assertEqual(removal.assignments(both)[-4:], ['-ExifByteOrder=Little-endian', '-IFD0:Orientation#=6', '-IFD0:YCbCrPositioning#=2', '-ExifIFD:ColorSpace#=1'])
        agrees = self.minimise('min-xmp-agrees.jpg')
        self.assertEqual(agrees['minimise']['preserved'], {'Orientation': 6})

    def test_a_file_without_removable_metadata_has_no_native_work(self):
        plan = self.minimise('edit-jfif-only.jpg')
        self.assertEqual((plan['present'], removal.assignments(plan), plan['blocks']), (False, [], []))

    def test_what_cannot_be_kept_faithfully_is_refused_with_a_stable_code(self):
        gamma = self.refusal('min-gamma.jpg', 'MINIMISE_RENDERING_UNPRESERVED')
        self.assertEqual(gamma.observed['tag'], 'Gamma')
        conflict = self.refusal('min-xmp-conflict.jpg', 'RENDERING_REPRESENTATION_CONFLICT')
        self.assertEqual((conflict.observed['property'], conflict.observed['exif']), ('tiff:Orientation', 6))
        self.assertEqual(self.refusal('min-orientation-nine.jpg', 'MINIMISE_RENDERING_UNPRESERVED').observed['tag'], 'Orientation')

    def test_the_closed_after_state_names_what_remains(self):
        item = self.item('edit-rich.jpg')
        kept = {'Orientation': 6}
        self.assertEqual(removal.exif_state_problems(item['payloads'], item['located'], item['walk'], kept)[:3], ['ifd:GPS', 'ifd:IFD1', 'IFD0:0x010E'])
        minimal = self.item('edit-jfif-only.jpg')
        self.assertEqual(removal.exif_state_problems(minimal['payloads'], minimal['located'], minimal['walk'], {}), [])

    def test_the_native_diff_explains_only_removals_and_the_declared_mandatory_values(self):
        def record(*rows):
            return {'observations': [{'group0': g0, 'group1': g1, 'name': n, 'value': v} for g0, g1, n, v in rows]}
        mini = {'jfif': [0, 1, 1], 'preserved': {'Orientation': 6}}
        before = record(('EXIF', 'IFD0', 'Make', 'Northfield'), ('EXIF', 'IFD0', 'Orientation', 6), ('XMP', 'XMP-dc', 'Title', 'T'), ('File', 'File', 'Comment', 'c'), ('JFIF', 'JFIF', 'XResolution', 1), ('File', 'File', 'ExifByteOrder', 'II'))
        after = record(('EXIF', 'IFD0', 'Orientation', 6), ('EXIF', 'IFD0', 'XResolution', 1), ('EXIF', 'IFD0', 'ResolutionUnit', 1), ('EXIF', 'IFD0', 'YCbCrPositioning', 1), ('JFIF', 'JFIF', 'XResolution', 1), ('File', 'File', 'ExifByteOrder', 'II'))
        diff = removal.minimise_diff(before, after, mini, False)
        self.assertEqual((diff['unexplained'], sorted(diff['targets'])), ([], ['EXIF:IFD0:Make', 'File:File:Comment', 'XMP:XMP-dc:Title']))
        self.assertEqual(sorted(s['rule'] for s in diff['sideEffects']), ['S4-exifResolution', 'S4-exifResolutionUnit', 'S4-yCbCrPositioning'])
        wrong = record(('EXIF', 'IFD0', 'Orientation', 3), ('EXIF', 'IFD0', 'Make', 'Other'), ('EXIF', 'IFD0', 'XResolution', 300), ('JFIF', 'JFIF', 'XResolution', 1))
        diff = removal.minimise_diff(before, wrong, mini, False)
        self.assertEqual(sorted(u['key'] for u in diff['unexplained']), ['EXIF:IFD0:Make', 'EXIF:IFD0:Orientation', 'EXIF:IFD0:XResolution', 'File:File:ExifByteOrder'])      # a byte order that vanishes while Exif stays is unexplained
        leftover = removal.minimise_native_residual(record(('EXIF', 'GPS', 'GPSLatitude', 12), ('EXIF', 'IFD0', 'Orientation', 6), ('File', 'File', 'Comment', 'c')), '$.items[0]')
        self.assertEqual([p['key'] for p in leftover], ['GPS:GPSLatitude', 'File:Comment'])

    def test_the_catalogue_data_is_pinned_and_keeps_rendering_metadata_out_of_every_selector(self):
        data = writes.minimise()
        self.assertEqual(data['deletes'], ['EXIF:all', 'XMP:all', 'IPTC:all', 'Photoshop:all'])
        self.assertEqual([e['name'] for e in data['preserve']], ['Orientation', 'YCbCrPositioning', 'ColorSpace', 'InteropIndex'])
        self.assertEqual(writes.digest(), writes.PIN)


class Native(Completion):
    """Real ExifTool 13.55: minimise, the qualifier refusal, the non-target proof through verify."""

    @classmethod
    def setUpClass(cls):
        cls.exe = executable()
        if cls.exe is None:
            raise unittest.SkipTest('real ExifTool 13.55 is not configured through SCHEMAXIS_EXIFTOOL')
        cls.tmp = Path(tempfile.mkdtemp(prefix='schemaxis-exiftool-complete-test-')).resolve()
        cls.addClassCleanup(shutil.rmtree, cls.tmp, ignore_errors=True)       # only the directory this class created
        cls.media = cls.tmp / 'media'
        cls.media.mkdir()
        for name, data in ALL.items():
            (cls.media / name).write_bytes(data)
        subprocess.run(['/usr/bin/perl', cls.exe, '-config', '', '-InteropIFD:InteropIndex=R98', '-o', str(cls.media / 'min-interop.jpg'), str(cls.media / 'min-colorspace.jpg')], check=True, capture_output=True, env={'LANG': 'C'})
        names = ['edit-rich.jpg', 'edit-rich-mm.jpg', 'edit-maker.jpg', 'min-colorspace.jpg', 'min-interop.jpg', 'min-gamma.jpg', 'min-xmp-conflict.jpg', 'min-xmp-agrees.jpg', 'edit-jfif-only.jpg', 'edit-trailer.jpg']
        cls.ids = [Path(n).stem.replace('-', '_') for n in names]
        items = [{'id': i, 'path': str(cls.media / n)} for i, n in zip(cls.ids, names)]
        cls.result = editing.run(doc('removeMetadata', items, categories=['minimise']), cls.tmp / 'minimise', executable=cls.exe, timeout=600)
        cls.directory = cls.tmp / 'minimise'

    def read(self, name):
        return (self.directory / 'photos' / (name + '.jpg')).read_bytes()

    def rendering(self, data):
        walk = jpegwrite.walk(data)
        return [(s['marker'], s['body']) for s in walk['pre'] if s['role'] == 'rendering'], data[walk['firstScan']:]

    def fields_of(self, path, names):
        located = containers.locate(Path(path).read_bytes())
        found = records.build(located, names, None, 'schemaxis.exiftool.fields/2')[1]
        return {n: (found[n]['state'], found[n]['canonical']) for n in names}

    def test_all_nine_fields_set_and_clear_and_all_six_categories_removed_natively(self):
        from schemaxis.adaptors.exiftool import catalogue
        self.assertEqual(catalogue.VERSION_MWG, 'schemaxis.exiftool.fields/2')
        everything = {'title': {'set': 'Nine fields'}, 'description': {'set': 'Line one.\nLine two.'}, 'keywords': {'set': ['k-one', 'k-two']}, 'creator': {'set': ['Ana Núñez', 'Smith; Jones']},
                      'copyright': {'set': '© 2026 Ana'}, 'rightsUrl': {'set': 'https://example.org/r'}, 'rating': {'set': 5}, 'locationCity': {'set': 'Zürich'}, 'locationCountry': {'set': 'Schweiz 🌄'}}
        items = [{'id': 'nine', 'path': str(self.media / 'edit-rich.jpg')}]
        editing.run(doc('editMetadata', items, edits=everything), self.tmp / 'nine', executable=self.exe, timeout=300)
        got = self.fields_of(self.tmp / 'nine' / 'photos' / 'nine.jpg', list(everything))
        self.assertEqual(got, {'title': ('present', 'Nine fields'), 'description': ('present', 'Line one.\nLine two.'), 'keywords': ('present', ('k-one', 'k-two')), 'creator': ('present', ('Ana Núñez', 'Smith; Jones')),
                               'copyright': ('present', '© 2026 Ana'), 'rightsUrl': ('present', 'https://example.org/r'), 'rating': ('present', 5), 'locationCity': ('present', 'Zürich'), 'locationCountry': ('present', 'Schweiz 🌄')})
        cleared = {name: {'clear': True} for name in everything}
        editing.run(doc('editMetadata', [{'id': 'nine', 'path': str(self.tmp / 'nine' / 'photos' / 'nine.jpg')}], edits=cleared), self.tmp / 'nine-clear', executable=self.exe, timeout=300)
        self.assertEqual({k: v[0] for k, v in self.fields_of(self.tmp / 'nine-clear' / 'photos' / 'nine.jpg', list(everything)).items()}, {k: 'absent' for k in everything})
        every = ['location', 'captureTime', 'deviceIdentity', 'descriptive', 'rights', 'thumbnails']
        editing.run(doc('removeMetadata', [{'id': 'six', 'path': str(self.media / 'edit-rich.jpg')}], categories=every), self.tmp / 'six', executable=self.exe, timeout=300)
        out = self.tmp / 'six' / 'photos' / 'six.jpg'
        absent = ['capturedLocal', 'capturedOffset', 'modifiedLocal', 'cameraMake', 'cameraModel', 'software', 'bodySerialNumber', 'lensSerialNumber', 'title', 'description', 'keywords', 'rating', 'creator', 'copyright', 'rightsUrl',
                  'gpsLatitude', 'gpsLongitude', 'locationCity']
        self.assertEqual({k: v[0] for k, v in self.fields_of(out, absent).items()}, {k: 'absent' for k in absent})
        self.assertEqual(self.fields_of(out, ['orientation']), {'orientation': ('present', 6)})                 # rendering metadata is never a removal target
        data = out.read_bytes()
        self.assertEqual(self.rendering(data), self.rendering(ALL['edit-rich.jpg']))
        self.assertEqual(thumbnail_of(data), None)
        for gone in (b'Northfield', b'SN-0001', b'Old Artist', b'Imaginary Town', b'a synthetic comment'):
            self.assertNotIn(gone, data)

    def test_every_item_has_its_exact_outcome_in_a_stable_slot(self):
        report = json.loads((self.directory / 'removal-report.json').read_text())
        outcomes = {r['id']: (r['status'], (r.get('fault') or {}).get('code')) for r in report['items']}
        self.assertEqual(outcomes, {'edit_rich': ('written', None), 'edit_rich_mm': ('written', None), 'edit_maker': ('written', None), 'min_colorspace': ('written', None), 'min_interop': ('written', None),
                                    'min_gamma': ('refused', 'MINIMISE_RENDERING_UNPRESERVED'), 'min_xmp_conflict': ('refused', 'RENDERING_REPRESENTATION_CONFLICT'), 'min_xmp_agrees': ('written', None),
                                    'edit_jfif_only': ('written', None), 'edit_trailer': ('refused', 'WRITE_TRAILER_UNSUPPORTED')})
        receipt = json.loads((self.directory / 'verification.json').read_text())
        self.assertEqual([(a['kind'], a['identity']['item']) for a in receipt['artifacts'][:10]], [('image' if outcomes[i][0] == 'written' else 'text', i) for i in self.ids])
        self.assertEqual((self.result['written'], self.result['refused'], self.result['nativeReplay']), (7, 3, 'fresh-replay-matched'))

    def test_the_encoded_image_and_the_rendering_segments_are_byte_identical_and_the_metadata_is_gone(self):
        for name, order, kept in (('edit_rich', 'II', {0x0112: 6}), ('edit_rich_mm', 'MM', {0x0112: 8}), ('edit_maker', 'II', {0x0112: 6})):
            out = self.read(name)
            source = ALL[name.replace('_', '-') + '.jpg']
            self.assertEqual(self.rendering(out), self.rendering(source), name)               # JFIF, Adobe, both ICC chunks, and everything from the first scan on
            for gone in (b'Northfield', b'NF-200', b'Old title', b'Old Artist', b'Imaginary Town', b'Shown City', b'SN-0001', b'a synthetic comment', b'MAKERNOTE-OPAQUE', b'Photoshop 3.0', b'xmpmeta'):
                self.assertNotIn(gone, out, (name, gone))
            payloads = records.Payloads(containers.locate(out))
            self.assertEqual((payloads.xmp[0], payloads.iptc[0]), ('absent', 'absent'))
            ifd0 = {e.tag: e.values() for e in removal.exif_entries(payloads, 'IFD0')}
            self.assertEqual(ifd0[0x0112], [kept[0x0112]])
            self.assertEqual(sorted(ifd0), [0x0112, 0x011A, 0x011B, 0x0128, 0x0213])        # Orientation plus the declared mandatory values: nothing else
            self.assertEqual(payloads.exif[1]['order'], '<' if order == 'II' else '>')         # the capture's byte order is kept
            self.assertEqual(set(payloads.exif[1]['ifds']), {'IFD0'})

    def test_colour_values_are_kept_and_the_interop_record_is_proved(self):
        out = self.read('min_colorspace')
        payloads = records.Payloads(containers.locate(out))
        self.assertEqual({e.tag: e.values() for e in removal.exif_entries(payloads, 'ExifIFD')}[0xA001], [1])
        self.assertEqual({e.tag: e.values() for e in removal.exif_entries(payloads, 'IFD0')}[0x0213], [2])
        interop = self.read('min_interop')
        self.assertEqual(removal.interop_index(containers.locate(interop)), 'R98')
        self.assertEqual(removal.interop_index(containers.locate(self.read('edit_rich'))), None)

    def test_a_file_without_removable_metadata_is_copied_unchanged_and_says_so(self):
        self.assertEqual(self.read('edit_jfif_only'), ALL['edit-jfif-only.jpg'])
        report = json.loads((self.directory / 'removal-report.json').read_text())
        row = next(r for r in report['items'] if r['id'] == 'edit_jfif_only')
        self.assertTrue(row['removed']['nothingToRemove'])
        self.assertEqual(row['arguments'], [])

    def test_minimise_is_idempotent_and_verifies_again(self):
        items = [{'id': 'again', 'path': str(self.directory / 'photos' / 'edit_rich.jpg')}]
        again = editing.run(doc('removeMetadata', items, categories=['minimise']), self.tmp / 'again', executable=self.exe, timeout=300)
        self.assertEqual((again['written'], again['nativeReplay']), (1, 'fresh-replay-matched'))
        self.assertEqual((self.tmp / 'again' / 'photos' / 'again.jpg').read_bytes(), self.read('edit_rich'))
        self.assertEqual(editing.verify(self.directory, executable=self.exe)['written'], 7)

    def test_the_residual_report_lists_what_stays_and_states_the_limits(self):
        residual = json.loads((self.directory / 'residual.json').read_text())
        row = next(r for r in residual['items'] if r['id'] == 'edit_rich')
        self.assertEqual(sorted({s['role'] for s in row['segments']}), ['coding', 'exif', 'rendering'])
        self.assertEqual(row['removed']['minimise']['preserved'], {'Orientation': 6})
        self.assertTrue(any('not anonymisation' in x for x in residual['limits']))
        self.assertTrue(any('pixel content' in x for x in residual['limits']))

    def mutate(self, name, change):
        target = self.tmp / ('mutant-' + name)
        shutil.copytree(self.directory, target, symlinks=True)
        change(target)
        with self.assertRaises(SchemaxisError) as caught:
            editing.verify(target, executable=self.exe)
        fault = caught.exception.fault
        cause = fault.observed.get('cause', {})
        return cause.get('code', fault.code), fault.location

    def tamper(self, relative, replace):
        def go(directory):
            path = directory / relative
            path.write_bytes(replace(path.read_bytes()))
        return go

    def test_minimise_mutants_fail_verify_with_one_exact_code_and_location(self):
        photo = 'photos/edit_rich.jpg'
        self.assertEqual(self.mutate('orientation', self.tamper(photo, lambda d: d.replace(b'\x12\x01\x03\x00\x01\x00\x00\x00\x06\x00', b'\x12\x01\x03\x00\x01\x00\x00\x00\x03\x00', 1))), ('MINIMISE_PRESERVED_CHANGED', '$.items[0].exif'))
        self.assertEqual(self.mutate('restore', lambda d: (d / photo).write_bytes((d / 'captured/edit_rich.jpg').read_bytes())), ('REMOVAL_RESIDUAL', '$.items[0].xmp'))
        self.assertEqual(self.mutate('icc', self.tamper(photo, lambda d: d.replace(b'mntr', b'mntR', 1))), ('RENDERING_SEGMENT_CHANGED', '$.items[0].image'))

        def scan(d):
            index = d.rindex(b'\xff\xda') + 14
            return d[:index] + bytes([d[index] ^ 0x40]) + d[index + 1:]
        self.assertEqual(self.mutate('scan', self.tamper(photo, scan)), ('IMAGE_DATA_CHANGED', '$.items[0].image'))

        def keep_comment(d):             # a comment segment survives the minimisation: the closed after-state names it before any integrity fault
            data = (d / photo).read_bytes()
            walk = jpegwrite.walk(data)
            comment = author.segment(0xFE, b'kept comment')
            index = walk['pre'][0]['offset'] + 2 + walk['pre'][0]['length']
            (d / photo).write_bytes(data[:index] + comment + data[index:])
        self.assertEqual(self.mutate('comment', keep_comment), ('REMOVAL_RESIDUAL', '$.items[0].comment'))

    def test_a_qualified_xmp_value_is_refused_not_flattened_and_an_untouched_one_survives(self):
        items = [{'id': 'bag', 'path': str(self.media / 'qual-bag.jpg')}, {'id': 'plain', 'path': str(self.media / 'edit-keywords.jpg')}]
        result = editing.run(doc('editMetadata', items, edits={'keywords': {'set': ['alpine', 'new']}}), self.tmp / 'qualified', executable=self.exe, timeout=300)
        self.assertEqual((result['written'], result['refused']), (1, 1))
        report = json.loads((self.tmp / 'qualified' / 'edit-report.json').read_text())
        fault = next(r['fault'] for r in report['items'] if r['id'] == 'bag')
        self.assertEqual((fault['code'], fault['location']), ('XMP_QUALIFIERS_WOULD_BE_LOST', '$.edits.keywords'))
        self.assertEqual((fault['observed']['property'], fault['observed']['qualifiers']), ('dc:subject', 1))
        outcome = json.loads((self.tmp / 'qualified' / 'outcomes' / 'bag.json').read_text())
        self.assertEqual((outcome['status'], outcome['image']), ('refused', False))
        with self.assertRaises(SchemaxisError) as caught:                 # a qualifier structure makes the creator unreadable as a plain list: refused as well (every item refused: no image)
            editing.run(doc('editMetadata', [{'id': 'seq', 'path': str(self.media / 'qual-struct.jpg')}], edits={'creator': {'set': ['Ana']}}), self.tmp / 'qualified-seq', executable=self.exe, timeout=300)
        self.assertEqual(caught.exception.fault.code, 'NO_USABLE_ITEMS')
        seq = json.loads((self.tmp / 'qualified-seq' / 'outcomes' / 'seq.json').read_text())
        self.assertEqual((seq['fault']['code'], seq['fault']['location']), ('EDIT_DESTINATION_UNREADABLE', '$.edits.creator'))
        title_only = editing.run(doc('editMetadata', items[:1], edits={'title': {'set': 'New title'}}), self.tmp / 'qualified-title', executable=self.exe, timeout=300)
        self.assertEqual(title_only['written'], 1)           # the qualified keyword is not rewritten, so its qualifier is proved intact by the native diff
        out = (self.tmp / 'qualified-title' / 'photos' / 'bag.jpg').read_bytes()
        self.assertIn(b"<rdf:li xml:lang='fr'>alpin</rdf:li>", out)      # ExifTool serialises attributes with single quotes

    def test_a_changed_maker_note_in_an_edited_output_fails_verify(self):
        items = [{'id': 'maker', 'path': str(self.media / 'edit-maker.jpg')}]
        editing.run(doc('editMetadata', items, edits={'title': {'set': 'Maker kept'}}), self.tmp / 'maker-edit', executable=self.exe, timeout=300)
        target = self.tmp / 'maker-mutant'
        shutil.copytree(self.tmp / 'maker-edit', target, symlinks=True)
        path = target / 'photos' / 'maker.jpg'
        data = path.read_bytes()
        self.assertIn(b'MAKERNOTE-OPAQUE-0123456789', data)
        path.write_bytes(data.replace(b'MAKERNOTE-OPAQUE-0123456789', b'MAKERNOTE-OPAQUE-012345678X'))
        with self.assertRaises(SchemaxisError) as caught:
            editing.verify(target, executable=self.exe)
        cause = caught.exception.fault.observed.get('cause', {})
        self.assertEqual((cause.get('code'), caught.exception.fault.location), ('MAKERNOTE_CHANGED', '$.items[0].exif'))
        self.assertEqual(editing.verify(self.tmp / 'maker-edit', executable=self.exe)['written'], 1)


class NativeFamily(Completion):
    """Real ExifTool 13.55: keyword add and remove (C4), the typed companion loss at the IPTC byte limit (C6) and exact Unicode forms (C2). Each expected value is a
    literal below and is read from the output bytes by the local IIM and XML parsers, never from ExifTool, the planner or the adaptor readers."""
    NFC = 'caf\u00e9 \u00c5ngstr\u00f6m'
    NFD = 'cafe\u0301 A\u030angstro\u0308m'
    OVER = '\u00e9' * 17                       # 34 UTF-8 bytes against the 32-byte By-line
    EXACT = '\u00e9' * 16                      # exactly 32 bytes
    PROOFS = ['readback', 'preservation', 'nativeDiff']
    BINARY = bytes(range(0x80, 0x8C))                    # a referenced Canon-note value of 12 bytes 0x80-0x8B

    @classmethod
    def setUpClass(cls):
        cls.exe = executable()
        if cls.exe is None:
            raise unittest.SkipTest('real ExifTool 13.55 is not configured through SCHEMAXIS_EXIFTOOL')
        cls.tmp = Path(tempfile.mkdtemp(prefix='schemaxis-exiftool-family-test-')).resolve()
        cls.addClassCleanup(shutil.rmtree, cls.tmp, ignore_errors=True)       # only the directory this class created
        cls.media = cls.tmp / 'media'
        cls.media.mkdir()
        for name, data in ALL.items():
            (cls.media / name).write_bytes(data)

    def run_edit(self, label, copies, edit_map, item_edits=(), **extra):
        """``copies``: {item id: fixture name}; the fixture bytes are copied under the id, so one fixture serves several items."""
        items = []
        for item_id, fixture in copies.items():
            (self.media / (item_id + '.jpg')).write_bytes(ALL[fixture])
            items.append({'id': item_id, 'path': str(self.media / (item_id + '.jpg'))})
        extra = {**extra, **({'itemEdits': [{'item': i, 'edits': e} for i, e in item_edits]} if item_edits else {})}
        result = editing.run(doc('editMetadata', items, edits=edit_map, **extra), self.tmp / label, executable=self.exe, timeout=600)
        report = json.loads((self.tmp / label / 'edit-report.json').read_text())
        return result, {r['id']: r for r in report['items']}

    def output(self, label, item_id):
        return (self.tmp / label / 'photos' / (item_id + '.jpg')).read_bytes()

    def assert_three_proofs_and_replay(self, label, result, written, items):
        self.assertEqual((result['written'], result['nativeReplay']), (written, 'fresh-replay-matched'))
        verified = editing.verify(self.tmp / label, executable=self.exe)            # R, P and N recomputed from the retained bytes, then a fresh native replay
        self.assertEqual((verified['written'], verified['proofs'], verified['nativeReplay']), (written, self.PROOFS, 'fresh-replay-matched'))
        for item_id, row in items.items():
            if row['status'] == 'written':
                self.assertEqual((row['proofs']['problems'], row['proofs']['N']['unexplained']), (0, 0), item_id)

    def untouched_image(self, label, item_id, fixture):
        after, before = self.output(label, item_id), ALL[fixture]
        self.assertEqual(scan_tail(after), scan_tail(before), item_id)            # the encoded image from the first scan header to the end

    def test_c4_keywords_add_and_remove_run_natively_with_literal_after_values(self):
        copies = {'kw_both': 'edit-keywords.jpg', 'kw_remove': 'edit-keywords.jpg', 'kw_add': 'edit-keywords.jpg', 'kw_conflict': 'edit-keywords-conflict.jpg'}
        source = ALL['edit-keywords.jpg']
        self.assertEqual(iim_values(source, 2, 25), [b'alpine', b'dawn', b'draft'])                                  # the concordant base, literal
        self.assertEqual(xmp_property(source, DC[1:-1], 'subject'), ('Bag', [(None, 'alpine'), (None, 'dawn'), (None, 'draft')]))
        result, rows = self.run_edit('c4', copies, {'keywords': {'add': ['new'], 'remove': ['draft']}},
                                     [('kw_remove', {'keywords': {'remove': ['dawn']}}), ('kw_add', {'keywords': {'add': ['new']}}), ('kw_conflict', {'keywords': {'add': ['x']}})])
        self.assertEqual((result['written'], result['refused'], result['setStatus']), (3, 1, 'partial'))
        expected = {'kw_both': ['alpine', 'dawn', 'new'], 'kw_remove': ['alpine', 'draft'], 'kw_add': ['alpine', 'dawn', 'draft', 'new']}
        for item_id, after in expected.items():
            data = self.output('c4', item_id)
            self.assertEqual(iim_values(data, 2, 25), [k.encode() for k in after], item_id)                         # IPTC keywords, in order
            self.assertEqual(xmp_property(data, DC[1:-1], 'subject'), ('Bag', [(None, k) for k in after]), item_id)  # one XMP Bag, same order
            self.assertEqual(iim_without(data, (2, 25)), iim_without(source, (2, 25)), item_id)                       # no other IIM dataset (title, creator, charset 1:90 ...) changed
            self.assertTrue(all(old in data for old in (b'Old description', b'Old Copyright', b'Old Artist', b'a synthetic comment')), item_id)     # untargeted EXIF text and the comment survive
            self.untouched_image('c4', item_id, 'edit-keywords.jpg')
            self.assertEqual(rows[item_id]['fields']['keywords']['value'], after)
            self.assertEqual(rows[item_id]['proofs']['R'], {'destinations': 2, 'fields': ['keywords']})
        self.assertNotIn(b'draft', self.output('c4', 'kw_both'))                                                     # removed from IPTC and XMP alike
        self.assert_three_proofs_and_replay('c4', result, 3, rows)
        refused = rows['kw_conflict']                                              # a conflicting base is refused by the host planner: no native write process exists for it
        self.assertEqual((refused['status'], refused['fault']['code'], refused['fault']['location']), ('refused', 'EDIT_BASE_CONFLICT', '$.edits.keywords'))
        self.assertEqual(sorted(refused['fault']['observed']['sources']), ['iptc', 'xmp'])
        self.assertFalse(list((self.tmp / 'c4').glob('write-kw_conflict*')))
        self.assertFalse((self.tmp / 'c4' / 'photos' / 'kw_conflict.jpg').exists())
        self.assertEqual(len(list((self.tmp / 'c4').glob('write-kw_*-submission.json'))), 3)

    def test_c6_a_companion_that_cannot_fit_is_removed_and_reported_never_truncated(self):
        rich, ascii_iptc = 'edit-rich.jpg', 'edit-ascii-iptc.jpg'
        copies = {'over34': rich, 'over34_ascii': ascii_iptc, 'over33': rich, 'exact32': rich, 'mixed': rich}
        result, rows = self.run_edit('c6', copies, {'creator': {'set': [self.OVER]}},
                                     [('over33', {'creator': {'set': [self.EXACT + 'a']}}), ('exact32', {'creator': {'set': [self.EXACT]}}), ('mixed', {'creator': {'set': [self.EXACT, self.OVER, 'Plain']}})])
        self.assertEqual((result['written'], result['refused'], result['setStatus']), (5, 0, 'complete'))
        self.assertEqual((len(self.OVER.encode()), len(self.EXACT.encode()), len((self.EXACT + 'a').encode())), (34, 32, 33))
        wanted = {'over34': [self.OVER], 'over34_ascii': [self.OVER], 'over33': [self.EXACT + 'a'], 'exact32': [self.EXACT], 'mixed': [self.EXACT, self.OVER, 'Plain']}
        loss = {'over34': 34, 'over34_ascii': 34, 'over33': 33, 'mixed': 34}
        for item_id, creators in wanted.items():
            data = self.output('c6', item_id)
            self.assertEqual(xmp_property(data, DC[1:-1], 'creator'), ('Seq', [(None, c) for c in creators]), item_id)       # the full intended XMP value, in order
            self.assertIn(('; '.join(creators)).encode() if len(creators) > 1 else creators[0].encode(), data, item_id)      # and the complete EXIF Artist (UTF-8)
            self.assertNotIn(b'Old Artist', data, item_id)                                                                   # the old, now wrong IPTC value is not retained anywhere
            if item_id == 'exact32':
                self.assertEqual(iim_values(data, 2, 80), [self.EXACT.encode()], item_id)                                    # exactly the limit fits: written complete, nothing lost
                self.assertEqual(rows[item_id]['losses'], [])
            else:
                self.assertEqual(iim_values(data, 2, 80), [], item_id)                                                       # the companion is absent, not a 32-byte prefix of the value
                self.assertEqual(rows[item_id]['losses'], [{'bytes': [loss[item_id]], 'destination': 'IPTC:By-line', 'field': 'creator', 'limit': 32, 'reason': 'iptcLength', 'treatment': 'companionRemoved'}], item_id)
            self.assertFalse([1 for r, d, v in iim(data) if v.startswith('\u00e9\u00e9'.encode())], item_id) if item_id != 'exact32' else None     # no dataset carries a prefix of the value
        for item_id, fixture in (('over34', rich), ('exact32', rich), ('over34_ascii', ascii_iptc)):
            data, source = self.output('c6', item_id), ALL[fixture]
            self.assertEqual(iim_without(data, (2, 80)), iim_without(source, (2, 80)), item_id)         # no other dataset changed, and the IIM character-set meaning is the same:
            self.assertEqual(iim_values(data, 1, 90), iim_values(source, 1, 90), item_id)               # UTF-8 stays declared for the rich file, none is added over the ASCII file
            self.untouched_image('c6', item_id, fixture)
        self.assertEqual(iim_values(self.output('c6', 'over34_ascii'), 1, 90), [])
        self.assertEqual(iim_values(self.output('c6', 'over34'), 1, 90), [b'\x1b%G'])
        self.assert_three_proofs_and_replay('c6', result, 5, rows)
        report = json.loads((self.tmp / 'c6' / 'edit-report.json').read_text())
        self.assertTrue(report['items'][0]['losses'] and report['items'][0]['proofs']['R']['fields'] == ['creator'])
        # the host refusal policy stops the same item before any native process exists, and the others of the set are still written
        refuse = self.run_edit('c6-refuse', {'r_over34': rich, 'r_exact32': rich}, {'creator': {'set': [self.OVER]}}, [('r_exact32', {'creator': {'set': [self.EXACT]}})], policies={'companionLoss': 'refuse'})
        self.assertEqual((refuse[0]['written'], refuse[0]['refused']), (1, 1))
        fault = refuse[1]['r_over34']['fault']
        self.assertEqual((fault['code'], refuse[1]['r_over34']['status']), ('COMPANION_LOSS_REFUSED', 'refused'))
        self.assertFalse(list((self.tmp / 'c6-refuse').glob('write-r_over34*')))
        self.assertTrue(list((self.tmp / 'c6-refuse').glob('write-r_exact32*')))

    def test_nfc_and_nfd_text_are_written_exactly_and_never_normalised(self):
        copies = {'nfc': 'edit-rich.jpg', 'nfd': 'edit-rich.jpg'}
        edit_map = {'title': {'set': self.NFC}, 'description': {'set': self.NFC}, 'creator': {'set': [self.NFC]}}
        result, rows = self.run_edit('nfd', copies, edit_map, [('nfd', {'title': {'set': self.NFD}, 'description': {'set': self.NFD}, 'creator': {'set': [self.NFD]}})])
        self.assertEqual((len(self.NFC), len(self.NFD)), (13, 16))
        self.assertEqual([ord(c) for c in self.NFD[:5]], [99, 97, 102, 101, 769])                    # literal code points: e followed by U+0301
        self.assertEqual([ord(c) for c in self.NFC[:4]], [99, 97, 102, 233])
        for item_id, text in (('nfc', self.NFC), ('nfd', self.NFD)):
            data = self.output('nfd', item_id)
            self.assertEqual(xmp_property(data, DC[1:-1], 'title'), ('Alt', [('x-default', text)]))
            self.assertEqual(xmp_property(data, DC[1:-1], 'creator'), ('Seq', [(None, text)]))
            self.assertEqual(iim_values(data, 2, 5), [text.encode()])                                # IPTC object name, UTF-8 under the declared character set
            self.assertEqual(iim_values(data, 2, 80), [text.encode()])
            self.assertEqual(iim_values(data, 1, 90), [b'\x1b%G'])
            self.assertEqual(iim_values(data, 2, 120), [text.encode()])
            self.assertIn(text.encode(), [body for marker, body in segments(data)[0] if marker == 0xE1 and body.startswith(b'Exif\0\0')][0])    # EXIF ImageDescription, UTF-8, unnormalised
        nfc_out, nfd_out = self.output('nfd', 'nfc'), self.output('nfd', 'nfd')
        self.assertNotIn(b'e\xcc\x81', nfc_out)                                                      # the precomposed form was not decomposed
        self.assertNotIn(b'caf\xc3\xa9', nfd_out)                                                    # and the decomposed form was not composed
        self.assertNotEqual(nfc_out, nfd_out)
        self.assert_three_proofs_and_replay('nfd', result, 2, rows)

    def canon_jpeg(self, **kw):
        import struct as st
        data = ALL['edit-jfif-only.jpg']
        app1 = b'Exif\0\0' + canon_tiff(**kw)
        index = 4 + int.from_bytes(data[4:6], 'big') if data[2:4] == b'\xff\xe0' else 2
        return data[:index] + b'\xff\xe1' + st.pack('>H', len(app1) + 2) + app1 + data[index:]

    def test_a_recognised_maker_note_that_moves_is_proved_by_relocation_and_its_unreferenced_bytes_are_reported(self):
        import hashlib
        (self.media / 'canon.jpg').write_bytes(self.canon_jpeg(blob=self.BINARY))
        long_artist = 'A much longer artist name'
        result = editing.run(doc('editMetadata', [{'id': 'canon', 'path': str(self.media / 'canon.jpg')}], edits={'creator': {'set': [long_artist]}}), self.tmp / 'canon', executable=self.exe, timeout=300)
        self.assertEqual((result['written'], result['refused']), (1, 0))
        row = json.loads((self.tmp / 'canon' / 'edit-report.json').read_text())['items'][0]
        self.assertEqual((row['proofs']['problems'], row['proofs']['N']['unexplained']), (0, 0))
        rebuilt = [e for e in row['proofs']['N']['sideEffects'] if e.get('rule') == 'S8-makerNoteRebuilt']
        out = self.output('canon', 'canon')
        before_tiff, after_tiff = canon_tiff(blob=self.BINARY), [body[6:] for marker, body in segments(out)[0] if marker == 0xE1 and body.startswith(b'Exif\0\0')][0]
        self.assertIn(long_artist.encode(), after_tiff)
        self.assertGreater(after_tiff.index(self.BINARY), before_tiff.index(self.BINARY))             # the note and its values really moved
        self.assertIn(b'Canon EOS SYNTH\0', after_tiff)
        self.assertEqual(len(rebuilt), 1)                                                                          # ExifTool 13.55 replaces the 8 unreferenced bytes (a footer): reported, not proved unchanged
        self.assertEqual(rebuilt[0]['unreferencedBefore'], [{'range': [58, 66], 'sha256': hashlib.sha256(b'SLACKSLK').hexdigest()}])
        self.assertEqual([x['range'] for x in rebuilt[0]['unreferencedAfter']], [[58, 66]])
        self.assertNotEqual(rebuilt[0]['unreferencedAfter'][0]['sha256'], rebuilt[0]['unreferencedBefore'][0]['sha256'])
        self.assertNotIn(b'SLACKSLK', after_tiff)
        self.assertEqual(rebuilt[0]['tiffOffset'], [86, 100])                                                      # the note moved by 14 bytes: its value offsets moved with it
        self.assertEqual(editing.verify(self.tmp / 'canon', executable=self.exe)['nativeReplay'], 'fresh-replay-matched')
        target = self.tmp / 'canon-mutant'
        shutil.copytree(self.tmp / 'canon', target, symlinks=True)
        path = target / 'photos' / 'canon.jpg'
        data = path.read_bytes()
        self.assertEqual(data.count(self.BINARY), 1)
        path.write_bytes(data.replace(self.BINARY, self.BINARY[:-1] + b'\x8c'))                                    # one byte of a referenced 12-byte binary value, same length: ExifTool lists such a value as '????????????'
        with self.assertRaises(SchemaxisError) as caught:
            editing.verify(target, executable=self.exe)
        cause = caught.exception.fault.observed.get('cause', {})
        self.assertEqual((cause.get('code'), caught.exception.fault.location), ('MAKERNOTE_CHANGED', '$.items[0].exif'))


class ReadLoopContext(unittest.TestCase):
    """The read-family agent loop reads a large registered qualification through the public bounded-page contract. The pages are produced by the real
    ``schemaxis.observations.bounded`` with the default budget; no native process and no API change are involved."""

    def loop(self, value):
        import qualify_exiftool_agent_loop as agent_loop
        from schemaxis.observations import bounded
        loop = agent_loop.Loop.__new__(agent_loop.Loop)
        loop.calls = []

        def call(method, **params):
            assert method == 'adaptor_context' and params.pop('version') == agent_loop.V
            loop.calls.append(dict(params))
            return bounded(value, 'adaptor/' + agent_loop.V, **params)
        loop.call = call
        return loop

    def test_a_small_unregistered_state_is_one_inline_value(self):
        state = {'status': 'unknown', 'reason': 'No scoped development-kit receipt is registered.'}
        loop = self.loop({'qualification': state})
        self.assertEqual(loop.context('/qualification'), (state, 'value', 1))
        self.assertEqual(loop.call('adaptor_context', version='schemaxis.exiftool/1', pointer='/qualification/status')['value'], 'unknown')

    def test_a_large_registered_receipt_is_paged_and_its_status_stays_a_scalar(self):
        receipt = {'documentVersion': 'schemaxis.exiftool/1', 'mode': 'native', 'verified': True, 'cases': [{'id': 'case-%d' % i, 'verified': True, 'runtime': 'exiftool 13.55', 'checks': ['x' * 40] * 6} for i in range(40)]}
        state = {'status': 'stale', 'receipt': receipt, 'scope': 'Only cited cases and recorded runtimes.'}
        loop = self.loop({'qualification': state})
        direct = loop.call('adaptor_context', version='schemaxis.exiftool/1', pointer='/qualification')
        self.assertEqual((direct['mode'], 'value' in direct), ('members', False))                        # the shape the integration saw: no inline value
        scalar = loop.call('adaptor_context', version='schemaxis.exiftool/1', pointer='/qualification/status')
        self.assertEqual((scalar['mode'], scalar['value']), ('value', 'stale'))
        whole, mode, pages = loop.context('/qualification', expand=False)
        self.assertEqual((mode, whole['status'], whole['scope'], whole['receipt']), ('members', 'stale', state['scope'], {'pointer': '/qualification/receipt', 'kind': 'object'}))
        for key in ('documentVersion', 'mode', 'verified'):
            self.assertEqual(loop.call('adaptor_context', version='schemaxis.exiftool/1', pointer='/qualification/receipt/' + key)['value'], receipt[key])
        full, mode, _ = loop.context('/qualification')                                                  # a complete paged read reproduces the object exactly
        self.assertEqual((mode, full), ('members', state))
        self.assertTrue(all(call.get('max_bytes', 8192) <= 8192 for call in loop.calls))                # the default budget was never raised


class MetadataFirst(Completion):
    """C17-C22: exact semantic mutants of published outputs. Every ordinary binding is refreshed and ``publication_metadata.verify`` must PASS before the
    public adaptor ``verify`` is asked, and only then is exactly one semantic code at exactly one location expected. Integrity mutants are tested separately."""
    RESULTS = {}

    @classmethod
    def setUpClass(cls):
        cls.exe = executable()
        if cls.exe is None:
            raise unittest.SkipTest('real ExifTool 13.55 is not configured through SCHEMAXIS_EXIFTOOL')
        cls.tmp = Path(tempfile.mkdtemp(prefix='schemaxis-exiftool-metadata-first-')).resolve()
        cls.addClassCleanup(shutil.rmtree, cls.tmp, ignore_errors=True)       # only the directory this class created
        cls.media = cls.tmp / 'media'
        cls.media.mkdir()
        for name, data in ALL.items():
            (cls.media / name).write_bytes(data)
        items = lambda *names: [{'id': Path(n).stem.replace('-', '_'), 'path': str(cls.media / n)} for n in names]
        cls.runs = {
            'edit': editing.run(doc('editMetadata', items('edit-rich.jpg', 'edit-rich-mm.jpg', 'edit-trailer.jpg'), edits={'title': {'set': 'Ridge at dawn'}, 'keywords': {'set': ['alpine', 'dawn']}, 'creator': {'set': ['Ana Núñez', 'Li Wei']}}), cls.tmp / 'edit', executable=cls.exe, timeout=300),
            'remove': editing.run(doc('removeMetadata', items('edit-rich.jpg', 'edit-rich-mm.jpg'), categories=['location', 'thumbnails', 'descriptive']), cls.tmp / 'remove', executable=cls.exe, timeout=300),
            'minimise': editing.run(doc('removeMetadata', items('edit-rich.jpg', 'edit-maker.jpg'), categories=['minimise']), cls.tmp / 'minimise', executable=cls.exe, timeout=300)}

    def tamper(self, run, relative, replace):
        def go(directory):
            path = directory / relative
            path.write_bytes(replace(path.read_bytes()))
        return go

    def mutate(self, label, run, change):
        old = self.tmp / run
        target = self.tmp / ('mut-%s-%s' % (run, label))
        shutil.copytree(old, target, symlinks=True)
        change(target)
        refresh(target, old)
        with self.assertRaises(SchemaxisError) as caught:
            adaptor.verify(target, executable=self.exe)
        fault = caught.exception.fault
        code = fault.observed.get('cause', {}).get('code', fault.code)
        MetadataFirst.RESULTS[label] = {'run': run, 'publicationMetadataVerified': True, 'route': 'public adaptor.verify after full refresh incl. publication_metadata.finalise and verify', 'code': code, 'location': fault.location, 'message': fault.message[:160]}
        return code, fault.location

    def test_a_refreshed_clean_run_verifies_through_the_public_route(self):
        for run in ('edit', 'remove', 'minimise'):
            target = self.tmp / ('clean-' + run)
            shutil.copytree(self.tmp / run, target, symlinks=True)
            refresh(target, self.tmp / run)
            self.assertTrue(adaptor.verify(target, executable=self.exe)['verified'], run)

    def test_c17_to_c20_wrong_value_list_shape_unrequested_change_and_side_effect_abuse(self):
        photo = 'photos/edit_rich.jpg'
        self.assertEqual(self.mutate('C17-wrong-value', 'edit', self.tamper('edit', photo, lambda d: d.replace(b'>Ridge at dawn</rdf:li>', b'>Ridge at dusk</rdf:li>', 1))), ('READBACK_MISMATCH', '$.items[0].fields.title.xmp'))
        self.assertEqual(self.mutate('C18-bag-to-seq', 'edit', self.tamper('edit', photo, lambda d: d.replace(b'rdf:Bag', b'rdf:Seq'))), ('READBACK_SHAPE_MISMATCH', '$.items[0].fields.keywords.xmp'))
        self.assertEqual(self.mutate('C19-unrequested-exif-change', 'edit', self.tamper('edit', photo, lambda d: d.replace(b'Synthetic fixture generator', b'Synthetic fixture generatoR'))), ('EXIF_NONTARGET_CHANGED', '$.items[0].exif'))
        self.assertEqual(self.mutate('C19-unrequested-xmp-device-property', 'edit', self.tamper('edit', photo, lambda d: d.replace(b'<tiff:Make>Northfield</tiff:Make>', b'<tiff:Make>Northfielx</tiff:Make>', 1))), ('NATIVE_UNEXPLAINED_CHANGE', '$.items[0].native'))
        self.assertEqual(self.mutate('C20-xmptoolkit', 'edit', self.tamper('edit', photo, lambda d: d.replace(b"x:xmptk='Image::ExifTool 13.55'", b"x:xmptk='Image::ExifTool 13.56'"))), ('NATIVE_UNEXPLAINED_CHANGE', '$.items[0].native'))

        def digest(d):
            index = d.index(b'8BIM\x04\x25') + 12
            return d[:index] + bytes([d[index] ^ 0x01]) + d[index + 1:]
        self.assertEqual(self.mutate('C20-iptc-digest-not-md5', 'edit', self.tamper('edit', photo, digest)), ('WRITE_OUTPUT_NATIVE_WARNING', '$.items[0].native'))       # ExifTool itself reports the stale digest

    def test_c21_image_dqt_icc_and_adobe_bytes(self):
        photo = 'photos/edit_rich.jpg'

        def scan(d):
            index = d.rindex(b'\xff\xda') + 14
            return d[:index] + bytes([d[index] ^ 0x40]) + d[index + 1:]

        def dqt(d):
            index = d.rindex(b'\xff\xdb', 0, d.rindex(b'\xff\xc0')) + 5       # the main image's table, not the embedded thumbnail's
            return d[:index] + bytes([d[index] ^ 0x01]) + d[index + 1:]
        self.assertEqual(self.mutate('C21-entropy', 'edit', self.tamper('edit', photo, scan)), ('IMAGE_DATA_CHANGED', '$.items[0].image'))
        self.assertEqual(self.mutate('C21-dqt', 'edit', self.tamper('edit', photo, dqt)), ('IMAGE_DATA_CHANGED', '$.items[0].image'))
        self.assertEqual(self.mutate('C21-icc', 'edit', self.tamper('edit', photo, lambda d: d.replace(b'mntr', b'mntR', 1))), ('RENDERING_SEGMENT_CHANGED', '$.items[0].image'))
        self.assertEqual(self.mutate('C21-adobe', 'edit', self.tamper('edit', photo, lambda d: d.replace(b'Adobe\0\x64', b'Adobe\0\x65', 1))), ('RENDERING_SEGMENT_CHANGED', '$.items[0].image'))

    def test_c22_residual_hiding_after_removal_and_minimise(self):
        restore = lambda d: (d / 'photos/edit_rich.jpg').write_bytes((d / 'captured/edit_rich.jpg').read_bytes())
        code, location = self.mutate('C22-removal-residual', 'remove', restore)
        self.assertEqual(code, 'REMOVAL_RESIDUAL')
        self.assertTrue(location.startswith('$.items[0].'), location)
        self.assertEqual(self.mutate('C22-minimise-residual', 'minimise', lambda d: (d / 'photos/edit_rich.jpg').write_bytes((d / 'captured/edit_rich.jpg').read_bytes())), ('REMOVAL_RESIDUAL', '$.items[0].xmp'))
        self.assertEqual(self.mutate('C22-minimise-orientation', 'minimise', self.tamper('minimise', 'photos/edit_rich.jpg', lambda d: d.replace(b'\x12\x01\x03\x00\x01\x00\x00\x00\x06\x00', b'\x12\x01\x03\x00\x01\x00\x00\x00\x03\x00', 1))), ('MINIMISE_PRESERVED_CHANGED', '$.items[0].exif'))
        self.assertEqual(self.mutate('C22-minimise-icc', 'minimise', self.tamper('minimise', 'photos/edit_rich.jpg', lambda d: d.replace(b'mntr', b'mntR', 1))), ('RENDERING_SEGMENT_CHANGED', '$.items[0].image'))

    def test_c24_slot_shift_and_false_outcome_are_integrity_faults_after_a_full_refresh(self):
        """Integrity (not semantic) mutants, still refreshed so that publication metadata verifies: a shifted artifact slot and a refused item reported as written."""
        def shift(directory):
            receipt = json.loads((directory / 'verification.json').read_text())
            receipt['artifacts'][0], receipt['artifacts'][2] = receipt['artifacts'][2], receipt['artifacts'][0]
            atomic_json(directory / 'verification.json', receipt)
        code, location = self.mutate('C24-slot-shift', 'edit', shift)
        self.assertEqual((code, location), ('VERIFICATION_FAILED', '$'))

        def false_success(directory):
            path = directory / 'edit-report.json'
            path.write_text(path.read_text().replace('"status": "refused"', '"status": "written"', 1))
        self.assertEqual(self.mutate('C24-false-outcome', 'edit', false_success), ('VERIFICATION_FAILED', 'edit-report.json'))

        def false_slot(directory):
            path = directory / 'outcomes' / 'edit_trailer.json'
            path.write_text(path.read_text().replace('"image": false', '"image": true', 1))
        self.assertEqual(self.mutate('C24-outcome-claims-image', 'edit', false_slot), ('VERIFICATION_FAILED', 'outcomes/edit_trailer.json'))


class Lifecycle(Completion):
    """C25/C26: a genuine WRITE-stage ExifTool Perl process is held, then the operation's own timeout or cancel ends it.

    The hold is a test-owned SIGSTOP applied after the real write process (system Perl, the ExifTool script, ``-o stage/ID.jpg captured/ID.jpg``) was
    observed with its launcher-bound inputs. It proves the timeout and the cancel reach a live write process and its group, never that they fired inside
    ExifTool's parser or at a particular byte of the output; the safety-net kill only runs in ``finally`` and fails the case if it was needed.
    """
    RESULTS = {}

    @classmethod
    def setUpClass(cls):
        cls.exe = executable()
        if cls.exe is None:
            raise unittest.SkipTest('real ExifTool 13.55 is not configured through SCHEMAXIS_EXIFTOOL')
        cls.tmp = Path(tempfile.mkdtemp(prefix='schemaxis-exiftool-lifecycle-test-')).resolve()
        cls.addClassCleanup(shutil.rmtree, cls.tmp, ignore_errors=True)       # only the directory this class created
        (cls.tmp / 'media').mkdir()
        (cls.tmp / 'media' / 'edit-rich.jpg').write_bytes(FILES['edit-rich.jpg'])

    def hold(self, label, document):
        directory = self.tmp / ('live-' + label)
        held, event = {}, threading.Event()
        perl = os.path.realpath('/usr/bin/perl')

        def watch():
            deadline = time.monotonic() + 90
            while time.monotonic() < deadline and not held:
                inputs = directory / 'write-live-inputs.json'
                if inputs.is_file() and inputs.stat().st_size:
                    for pid in descendants(os.getpid()):
                        try:
                            command = [c.decode() for c in Path('/proc/%d/cmdline' % pid).read_bytes().split(b'\0') if c]
                            image = os.path.realpath('/proc/%d/exe' % pid)
                            group = os.getpgid(pid)
                        except OSError:
                            continue
                        if len(command) > 3 and command[1] == str(self.exe) and '-o' in command and command[-1] == 'captured/live.jpg' and image == perl:
                            held.update(pid=pid, pgid=group, command=command, exe=image, boundInputs=json.loads(inputs.read_text()))
                            os.kill(pid, signal.SIGSTOP)
                            held['stopped'] = True
                            if label == 'cancel':
                                time.sleep(0.5)
                                event.set()
                            return
                time.sleep(0.02)
        watcher = threading.Thread(target=watch, daemon=True)
        watcher.start()
        started, safety_net = time.monotonic(), False
        try:
            with allocation({'threads': 1}, cancel=event):
                with self.assertRaises(SchemaxisError) as caught:
                    editing.run(document, directory, executable=self.exe, timeout=8 if label == 'timeout' else 120)
        finally:
            watcher.join(5)
            pid, pgid = held.get('pid'), held.get('pgid')
            if pid:
                end = time.monotonic() + 10
                while time.monotonic() < end and (pid_alive(pid) or group_alive(pgid)):
                    time.sleep(0.1)
                if pid_alive(pid) or group_alive(pgid):
                    safety_net = True
                    for sig in (signal.SIGCONT, signal.SIGKILL):
                        try:
                            os.kill(pid, sig)
                        except ProcessLookupError:
                            pass
        self.assertTrue(held.get('stopped'), 'the real write process was never observed before the hold')
        self.assertFalse(safety_net, 'the operation left the write process or its group alive')
        self.assertFalse(pid_alive(held['pid']) or group_alive(held['pgid']))
        self.assertEqual(held['pid'], held['pgid'])                                         # the write process leads its own process group
        self.assertNotEqual(held['pgid'], os.getpgid(0))
        fault = caught.exception.fault
        self.assertIn(fault.observed['exitCode'], (-15, -9))
        self.assertEqual(held['boundInputs'], {'files': {'captured/live.jpg': author_sha(FILES['edit-rich.jpg'])}})
        names = {x.name for x in directory.iterdir()}
        self.assertFalse(names & {'verification.json', 'manifest.json', 'edit-plan.json', 'edit-report.json', 'photos', 'outcomes', 'rejected', 'runtime.json', 'after.stdout'}, sorted(names))
        result = json.loads((directory / 'result.json').read_text())
        self.assertEqual((result['status'], result['fault']['code']), ('failed', fault.code))
        self.assertEqual((directory / 'version.stdout').read_bytes(), b'13.55\n')
        self.assertTrue((directory / 'before.stdout').is_file())                          # the read stages completed; the hold is on the WRITE stage only
        Lifecycle.RESULTS[label] = {'fault': fault.code, 'observedWritePid': held['pid'], 'observedProcessGroup': held['pgid'], 'pidEqualsPgid': True, 'procExe': held['exe'], 'argv': held['command'], 'launcherBoundInputs': held['boundInputs'],
                                    'dispatchLeaderExitCode': fault.observed['exitCode'], 'pidGone': True, 'processGroupGone': True, 'safetyNetKillNeeded': False, 'resultStatus': 'failed', 'noSuccessPublication': True,
                                    'elapsedSeconds': round(time.monotonic() - started, 2), 'stageHoldLimits': 'SIGSTOP applied after the launcher bound the inputs and a Perl write process was observed; no claim that the timeout or cancel fired inside the Perl parser or at a particular output byte'}
        return fault

    def document(self):
        return doc('editMetadata', [{'id': 'live', 'path': str(self.tmp / 'media' / 'edit-rich.jpg')}], edits={'title': {'set': 'Held write'}})

    def test_a_held_write_process_is_ended_by_the_timeout_and_nothing_is_published(self):
        self.assertEqual(self.hold('timeout', self.document()).code, 'RUNNER_TIMED_OUT')

    def test_a_held_write_process_is_ended_by_the_cancel_and_nothing_is_published(self):
        self.assertEqual(self.hold('cancel', self.document()).code, 'RUNNER_CANCELLED')


if __name__ == '__main__':
    unittest.main()
