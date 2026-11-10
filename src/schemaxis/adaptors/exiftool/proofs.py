"""Independent proofs of one rewritten item: readback (R), declared untouched IPTC meaning, and the closed native before/after diff (N).

R reads every requested value or absence back out of the written bytes with the standard-library readers and compares it with what the plan
requested, including list shape, language set and text exactly. N compares two fresh ExifTool listings of the capture and of the output key
by key (group and tag, instance tokens ignored): a change is either a target of the plan or one of a closed set of declared, value-aware side
effects; anything else is unexplained and fails the item. There is no ignored namespace. A listing from the same engine that wrote the file
is reproducibility evidence, not independent truth, which is why R and the preservation proofs do not depend on it.
"""
import hashlib
import struct

from schemaxis.adaptors.exiftool import codecs, edits, iptc as iptc_reader, jpegwrite, tiff, writes

FILE_UNCHANGED_GROUPS = ('File', 'ExifTool')
UTF8_RAW = '\x1b%G'
IIM_VERSION_TAGS = (('IPTC', 'IPTC', 'EnvelopeRecordVersion'), ('IPTC', 'IPTC', 'ApplicationRecordVersion'))


def problem(code, message, location, **observed):
    return {'code': code, 'message': message, 'location': location, **observed}


def iim_resources(walk, data):
    """``{id: body}`` of the Photoshop resources of the file's APP13 segment (empty when absent)."""
    for s in walk['pre']:
        if s['role'] == 'iptc':
            try:
                return dict(iptc_reader.resources(s['body']))
            except iptc_reader.Problem:
                return {}
    return {}


def iim_md5(walk, data):
    body = iim_resources(walk, data).get(0x0404)
    return None if body is None else hashlib.md5(body).hexdigest()


# ---------------------------------------------------------------- R: requested values and absence read back from the output
def expected_read(d, f, before):
    """What the independent reader must find at one destination after the write."""
    state = d['state']
    if state in ('skip', 'keep'):
        return before
    if state == 'delete':
        return {'state': 'absent'}
    value = f['value']
    family, shape = d['family'], f['shape']
    if family == 'xmp':
        if shape == 'langText':
            wanted = {'x-default': value['text'], **{e['language']: e['text'] for e in value['languages']}}
            if d['strayPolicy'] == 'keep':
                existing = before['value'] if before['state'] == 'present' and before['shape'] == 'langAlt' else {}
                for k in d['stray']:
                    wanted[k] = existing[k]
            return {'state': 'present', 'shape': 'langAlt', 'value': wanted}
        if shape in ('orderedList', 'unorderedList'):
            return {'state': 'present', 'shape': 'list', 'container': 'Seq' if shape == 'orderedList' else 'Bag', 'value': list(value)}
        return {'state': 'present', 'shape': 'text', 'value': str(value)}
    if family == 'iptc':
        return {'state': 'present', 'shape': 'datasets', 'value': list(d['strings'])}
    return {'state': 'present', 'shape': 'text', 'value': d['string']}


def compare_read(d, wanted, found):
    """``(code, message)`` of the first difference between an expected and an observed destination read, or ``None``."""
    if found['state'] == 'unreadable' or found.get('undecodable'):
        return 'READBACK_UNREADABLE', 'the written value cannot be read back (%s)' % (found.get('code') or found.get('undecodable'))
    if wanted['state'] == 'absent' or found['state'] == 'absent':
        if wanted['state'] != found['state']:
            return 'READBACK_MISMATCH', 'expected %s but the output has %s' % ('no value' if wanted['state'] == 'absent' else 'a value', found['state'])
        return None
    if wanted.get('raw') is not None and 'value' not in wanted:
        return None
    if wanted['shape'] != found['shape']:
        return 'READBACK_SHAPE_MISMATCH', 'expected a %s but the output holds a %s' % (wanted['shape'], found['shape'])
    if wanted['shape'] == 'list' and wanted['container'] != found['container']:
        return 'READBACK_SHAPE_MISMATCH', 'expected an rdf:%s but the output holds an rdf:%s' % (wanted['container'], found['container'])
    if wanted['shape'] == 'langAlt':
        a, b = {k.lower(): v for k, v in wanted['value'].items()}, {k.lower(): v for k, v in found['value'].items()}
        if a != b:
            return 'READBACK_MISMATCH', 'the language alternatives differ: expected %s, found %s' % (sorted(a), sorted(b))
        return None
    if wanted.get('raw') is not None and wanted['shape'] == 'datasets' and 'value' not in wanted:
        return None
    if wanted['value'] != found['value']:
        return 'READBACK_MISMATCH', 'the value read back differs from the requested value'
    return None


def readback(plan, before, after, at):
    """Compare every destination of every edited field; ``before`` and ``after`` are per-(field, family) destination reads of capture and output."""
    problems = []
    for name, f in plan['fields'].items():
        for d in f['destinations']:
            key = (name, d['family'])
            wanted = expected_read(d, f, before[key])
            if d['state'] in ('skip', 'keep'):
                same = {k: v for k, v in before[key].items()} == {k: v for k, v in after[key].items()}
                if not same:
                    problems.append(problem('READBACK_MISMATCH', 'a destination the plan leaves alone changed', '%s.fields.%s.%s' % (at, name, d['family']), destination=d['write']))
                continue
            result = compare_read(d, wanted, after[key])
            if result:
                problems.append(problem(result[0], result[1], '%s.fields.%s.%s' % (at, name, d['family']), destination=d['write']))
    return problems


def concordance(plan, fields_after, at):
    """E1 records of the output (MWG catalogue) must agree with the requested value wherever the field is set."""
    problems = []
    for name, f in plan['fields'].items():
        if f['action'] != 'set':
            continue
        record = fields_after[name]
        value = f['value']
        canonical = value['text'] if f['shape'] == 'langText' else tuple(value) if f['shape'] in ('orderedList', 'unorderedList') else value if f['shape'] != 'integer' else value
        if record['state'] != 'present' or record['canonical'] != canonical:
            problems.append(problem('CONCORDANCE_MISMATCH', 'the independent field record of the output is %s and does not agree with the requested value' % record['state'], '%s.fields.%s' % (at, name), reconciliation=record['reconciliation']))
    return problems


def datasets_of(payloads):
    state = payloads.iptc
    return state[1]['datasets'] if state[0] == 'ok' else {}


STRUCTURAL = {(1, 0), (1, 90), (2, 0)}


def iptc_emptied(before, after):
    """Whether the capture had IPTC text datasets and the output holds none (only structural datasets or no block at all)."""
    old, new = datasets_of(before), datasets_of(after)
    return any(k not in STRUCTURAL for k in old) and all(k in STRUCTURAL for k in new)


def charset_of(payloads):
    state = payloads.iptc
    return state[1]['charset'] if state[0] == 'ok' else None


def iptc_untouched(plan, before, after, at, extra_touched=()):
    """Every IPTC dataset outside the plan keeps its bytes, and a changed coded character set may not reinterpret any of them.
    ``extra_touched`` names datasets that another part of a composed plan (a transfer's time part) declares; it is empty for every plain E2 plan."""
    problems = []
    touched = set(extra_touched)
    for name, f in plan['fields'].items():
        for d in writes.fields()[name]['destinations']:
            if d['family'] == 'iptc':
                touched.add((d['record'], d['dataset']))
    ignore = {(1, 90), (1, 0), (2, 0)}
    old, new = datasets_of(before), datasets_of(after)
    if plan['iptc']['changed'] or before.iptc[0] == after.iptc[0] == 'ok':
        for key in sorted(set(old) | set(new)):
            if key in touched or key in ignore:
                continue
            if old.get(key) != new.get(key):
                problems.append(problem('IPTC_NONTARGET_CHANGED', 'an IPTC dataset the plan does not name changed', at + '.iptc', dataset='%d:%d' % key))
    cb, ca = charset_of(before), charset_of(after)
    if before.iptc[0] == 'ok' and cb != ca:
        legacy = [k for k, v in old.items() if k not in touched and edits.charset_scoped(k) and any(b > 127 for raw in v for b in raw)]
        if not plan['iptc']['assignCharset'] or legacy:
            problems.append(problem('IPTC_CHARSET_REINTERPRETED', 'the coded character set changed although untouched IPTC text exists whose meaning it would change', at + '.iptc', before=cb, after=ca, datasets=['%d:%d' % k for k in legacy][:8]))
    if before.iptc[0] == 'ok' and plan['iptc']['assignCharset'] is False and cb != ca:
        problems.append(problem('IPTC_CHARSET_UNDECLARED', 'the coded character set changed without the plan assigning it', at + '.iptc', before=cb, after=ca))
    return problems


POINTER_TAGS = {0x8769, 0x8825, 0xA005, 0x0201, 0x014A}      # IFD pointers and the thumbnail offset move whenever a block is rebuilt


def exif_entries_map(payloads):
    state = payloads.exif
    if state[0] != 'ok':
        return None
    found = {}
    for ifd, group in state[1]['ifds'].items():
        if group[0] == 'ok':
            for e in group[1]:
                found.setdefault((ifd, e.tag), []).append((e.kind, e.count, e.raw, e.oversize))
    return found


def raw_table(data, offset, order):
    """The raw rows ``(tag, kind, count, 4-byte value field)`` of one IFD, parsed here and not by the shared walker; ``None`` when damaged."""
    try:
        number = struct.unpack_from(order + 'H', data, offset)[0]
        if number > tiff.MAX_ENTRIES or offset + 2 + 12 * number + 4 > len(data):
            return None
        rows = []
        for index in range(number):
            base = offset + 2 + 12 * index
            tag, kind, count = struct.unpack_from(order + 'HHI', data, base)
            rows.append((tag, kind, count, data[base + 8:base + 12]))
        return rows
    except struct.error:
        return None


def sub_ifd(data, order, parent_offset, tag):
    """Offset of the IFD a LONG pointer entry of ``parent_offset`` names, or ``None``."""
    rows = raw_table(data, parent_offset, order)
    for t, kind, count, field in rows or ():
        if t == tag and kind == 4 and count == 1:
            return struct.unpack(order + 'I', field)[0]
    return None


def exif_ifd_offset(data):
    try:
        order, first = tiff.header(data)
    except tiff.Damaged:
        return None, None
    return order, sub_ifd(data, order, first, 0x8769)


def maker_note_of(data):
    """``(order, offset in the TIFF payload, note bytes)`` of the ExifIFD maker note read by the local parser, or ``None``."""
    order, exif = exif_ifd_offset(data)
    for tag, kind, count, field in (raw_table(data, exif, order) or ()) if exif else ():
        length = tiff.TYPES.get(kind, (None, 0))[1] * count
        if tag == 0x927C and length > 4:
            where = struct.unpack(order + 'I', field)[0]
            if 8 <= where and where + length <= len(data):
                return order, where, data[where:where + length]
    return None


def walk_note(note, start, order):
    """A maker note laid out as one plain IFD whose value offsets are TIFF-relative (the Canon layout): ``(entries, covered ranges)`` or ``None`` when it is not
    that layout. Entries are ``(tag, kind, count, inline bytes or None, value bytes or None, position inside the note or None)``."""
    rows = raw_table(note, 0, order)
    if rows is None:
        return None
    table_end = 2 + 12 * len(rows) + 4
    entries, covered = [], [(0, table_end)]            # the table including its next-IFD pointer, which is compared as the last entry
    for tag, kind, count, field in rows:
        size = tiff.TYPES.get(kind, (None, 0))[1]
        if not size:
            return None
        length = size * count
        if length <= 4:
            entries.append((tag, kind, count, field[:length], None, None))
            continue
        position = struct.unpack(order + 'I', field)[0] - start
        if position < table_end or position + length > len(note):
            return None
        entries.append((tag, kind, count, None, note[position:position + length], position))
        covered.append((position, position + length))
    entries.append(('next', 0, 0, note[table_end - 4:table_end], None, None))
    return entries, sorted(covered)


def unreferenced(note, covered):
    """The byte ranges of the note that its own IFD structure does not reference (padding, trailers, footers), as ``[(start, end, sha256)]``."""
    found, cursor = [], 0
    for begin, end in covered + [(len(note), len(note))]:
        if begin > cursor:
            found.append((cursor, begin, hashlib.sha256(note[cursor:begin]).hexdigest()))
        cursor = max(cursor, end)
    return found


def maker_note_check(before_tiff, after_tiff, at):
    """Relocation-aware independent comparison of a changed maker note: ``(problems, side effect or None)``.

    Provable: a note that is one plain IFD (value offsets relative to the TIFF header) whose entries keep tag, type, count, inline bytes, value bytes
    and relative position. A note that moved changes only its offset fields, by the one delta of its own move. Bytes the note's IFD structure does not
    reference (padding, a footer ExifTool adds) are not proved unchanged; when they differ they are a declared per-item side effect with hashes and ranges.
    Any other layout that changed is refused: this proof cannot show that a rebuilt vendor structure kept its meaning.
    """
    one, two = maker_note_of(before_tiff), maker_note_of(after_tiff)
    if one is None or two is None:
        return [problem('MAKERNOTE_CHANGED', 'the maker note cannot be read from both files for an independent comparison', at + '.exif', entry='ExifIFD:0x927C')], None
    (order1, start1, note1), (order2, start2, note2) = one, two
    walked = (walk_note(note1, start1, order1), walk_note(note2, start2, order2))
    if order1 != order2 or None in walked:
        return [problem('MAKERNOTE_CHANGED', 'the maker note changed and its layout is not a plain IFD with TIFF-relative offsets, so a relocation cannot be proved', at + '.exif', entry='ExifIFD:0x927C', before=len(note1), after=len(note2))], None
    (entries1, covered1), (entries2, covered2) = walked
    if entries1 != entries2:
        changed = [e1[0] for e1, e2 in zip(entries1, entries2) if e1 != e2][:8] or ['entry count']
        return [problem('MAKERNOTE_CHANGED', 'a maker note entry (tag, type, count, inline bytes, value bytes or position) differs from the capture', at + '.exif', entry='ExifIFD:0x927C', tags=['0x%04X' % t if isinstance(t, int) else t for t in changed])], None
    gaps1, gaps2 = unreferenced(note1, covered1), unreferenced(note2, covered2)
    if gaps1 == gaps2 and len(note1) == len(note2):
        return [], None
    return [], {'rule': 'S8-makerNoteRebuilt', 'entry': 'ExifIFD:0x927C', 'tiffOffset': [start1, start2], 'noteBytes': [len(note1), len(note2)],
                'unreferencedBefore': [{'range': [a, b], 'sha256': h} for a, b, h in gaps1[:8]], 'unreferencedAfter': [{'range': [a, b], 'sha256': h} for a, b, h in gaps2[:8]]}


def interop_rows(data):
    """Every row of the Interop IFD (ExifIFD pointer 0xA005) as ``(tag, kind, count, value bytes)``, from the local parser, or ``None``."""
    order, exif = exif_ifd_offset(data)
    where = sub_ifd(data, order, exif, 0xA005) if exif else None
    rows = raw_table(data, where, order) if where else None
    if rows is None:
        return None
    found = []
    for tag, kind, count, field in rows:
        length = tiff.TYPES.get(kind, (None, 0))[1] * count
        if length > 4:
            position = struct.unpack(order + 'I', field)[0]
            found.append((tag, kind, count, data[position:position + length] if position + length <= len(data) else None))
        else:
            found.append((tag, kind, count, field[:length]))
    return found


def exif_nontarget(before, after, targets, deleted_ifds, at, tiffs=None, effects=None):
    """Every Exif entry the plan does not name keeps its type, count and value bytes (compared by the independent walker, not by ExifTool).

    IFD pointers and the thumbnail offset are relocated by design and the thumbnail itself is compared separately. The Interop IFD (not enumerated by the
    shared walker) is compared by the local parser. A maker note must be byte-identical; when it differs, ``tiffs`` (the two raw TIFF payloads) allow the
    relocation-aware comparison of ``maker_note_check``, whose declared side effect is appended to ``effects``. Sub-IFDs (0x014A) are not enumerated: they are
    proved only by the native diff.
    """
    one, two = exif_entries_map(before), exif_entries_map(after)
    if one is None or two is None:
        return []
    problems = []
    for key in sorted(set(one) | set(two)):
        ifd, tag = key
        if tag in POINTER_TAGS or key in targets or ifd in deleted_ifds or one.get(key) == two.get(key):
            continue
        if tag == 0x927C and key in one and key in two and tiffs is not None:
            found, effect = maker_note_check(tiffs[0], tiffs[1], at)
            problems += found
            if effect is not None and effects is not None:
                effects.append(effect)
            continue
        code = 'MAKERNOTE_CHANGED' if tag == 0x927C else 'EXIF_NONTARGET_CHANGED'
        problems.append(problem(code, 'an Exif entry the plan does not name differs from the capture (%s)' % ('absent' if key not in two else 'appeared' if key not in one else 'value bytes differ'), at + '.exif', entry='%s:0x%04X' % key))
    if tiffs is not None and ('ExifIFD' not in deleted_ifds):
        rows_before, rows_after = interop_rows(tiffs[0]), interop_rows(tiffs[1])
        if rows_before != rows_after:
            problems.append(problem('EXIF_NONTARGET_CHANGED', 'the Interop IFD differs from the capture (%s)' % ('absent' if rows_after is None else 'appeared' if rows_before is None else 'entries differ'), at + '.exif', entry='Interop'))
    return problems[:12]


# ---------------------------------------------------------------- N: closed native before/after diff
def native_map(record):
    """``{(group0, group1, name): [values in listing order]}``: instance tokens are dropped, the order of copies kept."""
    found = {}
    for o in record['observations']:
        found.setdefault((o['group0'], 'IPTC' if (o['group0'], o['group1']) == ('IPTC', 'IPTC2') else o['group1'], o['name']), []).append(o['value'])     # IPTC2: the IPTC of a Photoshop resource block, see listing.alias_group
    return found


def text_of(values):
    out = []
    for v in values:
        out.extend(v if isinstance(v, list) else [v])
    return [str(x) for x in out]


def target_keys(plan, extra=()):
    """Group-qualified names (``group1:name``) of everything the plan writes or deletes, with language variants of language alternatives."""
    keys, prefixes = set(extra), set()
    for name, f in plan['fields'].items():
        for d in f['destinations']:
            if d['state'] in ('write', 'delete'):
                keys.add(d['listing'])
                if f['shape'] == 'langText' and d['family'] == 'xmp':
                    prefixes.add(d['listing'] + '-')
    return keys, prefixes


def is_target(key, keys, prefixes):
    qualified = '%s:%s' % (key[1], key[2])
    return qualified in keys or any(qualified.startswith(p) for p in prefixes)


def side_effect(key, before, after, ctx):
    """The id of the declared, value-aware side effect that explains this change, or ``None``."""
    group0, group1, name = key
    a, b = text_of(before or []), text_of(after or [])
    extra = ctx.get('extra')              # declared side effects of an operation family beyond the closed E2 set (the E3 write family adds the byte order of a created Exif block)
    if extra is not None:
        rule = extra(key, a, b)
        if rule:
            return rule
    if (group1, name) == ('XMP-x', 'XMPToolkit'):
        return 'S5-xmpToolkit' if ctx['xmpWritten'] and b == [edits.TOOLKIT] else None
    if ctx.get('iptcEmptied') and not b and a and ((group0, group1, name) in (*IIM_VERSION_TAGS, ('IPTC', 'IPTC', 'CodedCharacterSet')) or (group1, name) == ('Photoshop', 'IPTCDigest')):
        return 'S6-iptcEmptied'          # every dataset was cleared, so ExifTool dropped the whole IIM block with its structural datasets and digest
    if (group0, group1, name) == ('IPTC', 'IPTC', 'CodedCharacterSet'):
        return 'S6-iptcCharset' if ctx['assignCharset'] and not a and b == [UTF8_RAW] else None
    if (group0, group1, name) in IIM_VERSION_TAGS:
        return 'S6-iptcRecordVersion' if ctx['iptcChanged'] and not a and b == ['4'] else None
    if (group1, name) == ('Photoshop', 'IPTCDigest'):
        return 'S7-iptcDigest' if ctx['digest'] and ctx['afterIimMd5'] and b == [ctx['afterIimMd5']] else None
    if (group1, name) == ('File', 'CurrentIPTCDigest'):
        return 'S7-currentDigest' if ctx['iptcChanged'] and ((ctx['afterIimMd5'] and b == [ctx['afterIimMd5']]) or (ctx['afterIimMd5'] is None and not b)) else None
    if (group1, name) == ('IFD1', 'ThumbnailOffset'):
        return 'S3-thumbnailOffset' if ctx['thumbnailSame'] and len(a) == len(b) == 1 else None
    return None


def native_diff(before, after, plan, ctx, extra_targets=(), extra_prefixes=(), extra_group0=()):
    """Classify every native key whose values differ between the capture and the output listing."""
    one, two = native_map(before), native_map(after)
    keys, prefixes = target_keys(plan, extra_targets)
    prefixes |= set(extra_prefixes)
    out = {'targets': [], 'sideEffects': [], 'renumbered': [], 'unexplained': []}
    for key in sorted(set(one) | set(two)):
        a, b = one.get(key), two.get(key)
        if a == b:
            continue
        label = '%s:%s:%s' % key
        if a is not None and b is not None and len(a) > 1 and sorted(map(repr, a)) == sorted(map(repr, b)):
            out['renumbered'].append(label)
            continue
        if is_target(key, keys, prefixes) or key[0] in extra_group0:
            out['targets'].append(label)
            continue
        rule = side_effect(key, a, b, ctx)
        if rule:
            out['sideEffects'].append({'key': label, 'rule': rule})
            continue
        out['unexplained'].append({'key': label, 'before': text_of(a or [])[:6], 'after': text_of(b or [])[:6]})
    return out
