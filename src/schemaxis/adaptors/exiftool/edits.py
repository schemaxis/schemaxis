"""Typed edit planning for ``editMetadata``: value domain, per-destination decisions, native assignments and expected readback.

Authored input is a closed domain intent (set, clear, list add/remove of catalogue fields). Everything below turns that into one explicit
per-item plan from the independently read capture: which destination is written, deleted, left alone or refused and why, the exact native
assignments, and what an independent reader must find in the output. Losses are decided here, before any native process, and are never
truncations: a value that a companion form cannot hold exactly is either removed from that form (and reported) or the item is refused.
Text is never normalised, trimmed, case-folded or transliterated; lists are never flattened into strings except into the one MWG creator
join that the Artist reader splits back unambiguously.
"""
import re

from schemaxis.adaptors.exiftool import codecs, writes
from schemaxis.adaptors.exiftool import xmp as xmp_reader

LANGUAGE = re.compile(r'[A-Za-z]{1,8}(-[A-Za-z0-9]{1,8})*')
URL = re.compile(r'https?://[^\s/?#][^\s]*', re.ASCII)
MAX_LANGUAGES = 16
POLICY_DEFAULTS = {'iptc': 'ifPresent', 'otherLanguages': 'keep', 'exifEncoding': 'utf8', 'companionLoss': 'removeCompanion'}
POLICY_VALUES = {'iptc': ('ifPresent', 'always'), 'otherLanguages': ('keep', 'remove', 'refuse'), 'exifEncoding': ('utf8', 'ascii'), 'companionLoss': ('removeCompanion', 'refuse')}
TOOLKIT = 'Image::ExifTool 13.55'


class Refusal(Exception):
    """A per-item refusal decided before any native write: a stable code, a location and observed facts."""

    def __init__(self, code, message, location='$', **observed):
        super().__init__(message)
        self.code, self.message, self.location, self.observed = code, message, location, observed


class PlanError(Exception):
    """A set-level authored problem found while normalising (the caller turns it into a schemaxis fault)."""

    def __init__(self, code, message, location, **observed):
        super().__init__(message)
        self.code, self.message, self.location, self.observed = code, message, location, observed


# ---------------------------------------------------------------- value domain
def check_text(value, limits, at, field, item=False):
    """Exact text rules: not empty, no edge white space, no controls (LF only where the field allows it), no non-characters or lone surrogates."""
    if not isinstance(value, str):
        raise PlanError('INVALID_ARGUMENT', 'expected text', at, field=field)
    if value == '' or value.strip() == '':
        raise PlanError('EDIT_EMPTY_VALUE', 'an empty or white-space-only value reads back as absent; use clear to remove a value', at, field=field)
    if value != value.strip():
        raise PlanError('EDIT_VALUE_INVALID', 'leading or trailing white space is refused because it would not read back identically', at, field=field)
    allow_lf = limits.get('allowLF', False)
    for position, c in enumerate(value):
        code = ord(c)
        if (code < 32 and not (code == 10 and allow_lf)) or 0x7F <= code <= 0x9F or 0xD800 <= code <= 0xDFFF or code in (0xFFFE, 0xFFFF) or code in (0x2028, 0x2029):
            raise PlanError('EDIT_VALUE_INVALID', 'a control character, line separator, non-character or lone surrogate is refused', at, field=field, codePoint='U+%04X' % code, position=position)
    maximum = limits.get('itemMaxChars' if item else 'maxChars')
    if maximum is not None and len(value) > maximum:
        raise PlanError('EDIT_VALUE_TOO_LONG', 'the value exceeds %d characters' % maximum, at, field=field, characters=len(value))
    return value


def normalise_lang(value, limits, at, field):
    """The closed langText form ``{'text', 'languages': [{'language', 'text'}]}`` of a string shorthand or object."""
    if isinstance(value, str):
        return {'text': check_text(value, limits, at, field), 'languages': []}
    text = check_text(value['text'], limits, at + '.text', field)
    languages, seen = [], set()
    for index, entry in enumerate(value.get('languages', [])):
        place = '%s.languages[%d]' % (at, index)
        language = entry['language']
        if language.lower() == 'x-default':
            raise PlanError('INVALID_ARGUMENT', 'x-default is the text itself; list only other languages', place + '.language', field=field)
        if not LANGUAGE.fullmatch(language):
            raise PlanError('INVALID_ARGUMENT', 'use an RFC 3066 language tag such as fr or pt-BR', place + '.language', field=field, value=language[:40])
        if language.lower() in seen:
            raise PlanError('EDIT_DUPLICATE_LANGUAGE', 'a language is listed twice (tags are compared case-insensitively)', place + '.language', field=field, value=language)
        seen.add(language.lower())
        languages.append({'language': language, 'text': check_text(entry['text'], limits, place + '.text', field)})
    if len(languages) > MAX_LANGUAGES:
        raise PlanError('INVALID_ARGUMENT', 'at most %d other languages' % MAX_LANGUAGES, at + '.languages', field=field)
    return {'text': text, 'languages': languages}


def normalise_list(items, limits, at, field):
    if len(items) > limits['maxItems']:
        raise PlanError('INVALID_ARGUMENT', 'at most %d items' % limits['maxItems'], at, field=field)
    out, seen = [], set()
    for index, value in enumerate(items):
        text = check_text(value, limits, '%s[%d]' % (at, index), field, item=True)
        if text in seen:
            raise PlanError('EDIT_DUPLICATE_ITEM', 'an exact duplicate list item is refused (case-different items are distinct)', '%s[%d]' % (at, index), field=field, value=text[:60])
        seen.add(text)
        out.append(text)
    return out


def normalise_edit(field, edit, at):
    """One field edit in its closed form: ``{'set': v}``, ``{'clear': True}`` or ``{'add': [...], 'remove': [...]}`` (keyword-style lists only)."""
    spec = writes.fields()[field]
    shape, limits = spec['shape'], spec['limits']
    kinds = [k for k in ('set', 'clear', 'add', 'remove') if k in edit]
    if not kinds or ('set' in edit or 'clear' in edit) and len(kinds) > 1:
        raise PlanError('EDIT_INVALID', 'give exactly one of set, clear, or (for keyword-style lists) add and/or remove', at, field=field)
    if 'clear' in edit:
        if edit['clear'] is not True:
            raise PlanError('EDIT_INVALID', 'clear must be true', at + '.clear', field=field)
        return {'clear': True}
    if 'set' in edit:
        value = edit['set']
        if shape in ('orderedList', 'unorderedList'):
            if not isinstance(value, list) or not value:
                raise PlanError('EDIT_EMPTY_VALUE', 'a list needs at least one item; use clear to remove it', at + '.set', field=field)
            return {'set': normalise_list(value, limits, at + '.set', field)}
        if shape == 'langText':
            return {'set': normalise_lang(value, limits, at + '.set', field)}
        if shape == 'integer':
            if isinstance(value, bool) or not isinstance(value, int) or not limits['minimum'] <= value <= limits['maximum']:
                raise PlanError('EDIT_VALUE_INVALID', 'use an integer from %d to %d' % (limits['minimum'], limits['maximum']), at + '.set', field=field)
            return {'set': value}
        text = check_text(value, limits, at + '.set', field)
        if shape == 'url' and not URL.fullmatch(text):
            raise PlanError('EDIT_VALUE_INVALID', 'use an absolute http or https URL without white space', at + '.set', field=field)
        return {'set': text}
    if shape != 'unorderedList':
        raise PlanError('EDIT_INVALID', 'add and remove are only offered for keyword-style lists; replace an ordered list with set', at, field=field)
    result = {}
    for kind in ('add', 'remove'):
        if kind in edit:
            if not isinstance(edit[kind], list) or not edit[kind]:
                raise PlanError('EDIT_EMPTY_VALUE', kind + ' needs at least one item', '%s.%s' % (at, kind), field=field)
            result[kind] = normalise_list(edit[kind], limits, '%s.%s' % (at, kind), field)
    if set(result.get('add', [])) & set(result.get('remove', [])):
        raise PlanError('EDIT_INVALID', 'an item cannot be both added and removed', at, field=field)
    return result


def normalise_policies(policies):
    out = dict(POLICY_DEFAULTS)
    for key, value in (policies or {}).items():
        if value not in POLICY_VALUES[key]:
            raise PlanError('INVALID_ARGUMENT', 'policy %s accepts %s' % (key, ', '.join(POLICY_VALUES[key])), '$.policies.' + key)
        out[key] = value
    return out


# ---------------------------------------------------------------- independent reads of one destination
def ascii_text(text):
    return all(ord(c) < 128 for c in text)


def charset_scoped(key):
    """Whether the coded character set (IPTC 1:90) decides the text meaning of the dataset ``(record, number)``.

    ExifTool 13.55 decodes every string dataset of the application and news-photo records 2 to 6 through it (``ProcessIPTC``: ``$rec < 7``); the
    IIM specification applies the declared set to the envelope as well, so the envelope's other datasets are treated as at risk too. A changed
    shared set can therefore reinterpret any untouched dataset of records 1 to 6, not only record 2.
    """
    return 1 <= key[0] <= 6 and key != (1, 90)


def read_xmp(payloads, d):
    state = payloads.xmp
    if state[0] == 'notApplicable':
        return {'state': 'notApplicable'}
    if state[0] == 'absent':
        return {'state': 'absent'}
    if state[0] != 'ok':
        return {'state': 'unreadable', 'code': state[2] if state[0] == 'error' else state[1]}
    found = state[1].get(d['property'])
    if not found:
        return {'state': 'absent'}
    if len(found) > 1:
        return {'state': 'unreadable', 'code': 'XMP_PROPERTY_REPEATED'}
    o = found[0]
    if o['kind'] == 'struct':
        return {'state': 'unreadable', 'code': 'XMP_STRUCTURE'}
    if o['kind'] == 'langAlt':
        if o.get('duplicateLanguage'):
            return {'state': 'unreadable', 'code': 'XMP_LANG_DUPLICATE'}
        return {'state': 'present', 'shape': 'langAlt', 'value': dict(o['value'])}
    if o['kind'] == 'list':
        return {'state': 'present', 'shape': 'list', 'container': o['container'], 'value': list(o['value'])}
    return {'state': 'present', 'shape': 'text', 'value': o['value']}


def read_iptc(payloads, d):
    state = payloads.iptc
    if state[0] == 'notApplicable':
        return {'state': 'notApplicable'}
    if state[0] == 'absent':
        return {'state': 'absent'}
    if state[0] != 'ok':
        return {'state': 'unreadable', 'code': state[2] if state[0] == 'error' else state[1]}
    raws = state[1]['datasets'].get((d['record'], d['dataset']))
    if not raws:
        return {'state': 'absent'}
    out = {'state': 'present', 'shape': 'datasets', 'raw': [r.hex() for r in raws]}
    try:
        out['value'] = [codecs.iptc_text_of(r, state[1]['charset']) for r in raws]
    except codecs.ValueProblem as problem:
        out['undecodable'] = problem.code
    return out


def read_exif(payloads, d):
    state = payloads.exif
    if state[0] == 'notApplicable':
        return {'state': 'notApplicable'}
    if state[0] == 'absent':
        return {'state': 'absent'}
    if state[0] != 'ok':
        return {'state': 'unreadable', 'code': state[2] if state[0] == 'error' else state[1]}
    group = state[1]['ifds'].get(d['ifd'])
    if group is None:
        return {'state': 'absent'}
    if group[0] == 'error':
        return {'state': 'unreadable', 'code': group[1]}
    entries = [e for e in group[1] if e.tag == int(d['tag'], 16)]
    if not entries:
        return {'state': 'absent'}
    if len(entries) > 1:
        return {'state': 'unreadable', 'code': 'EXIF_TAG_REPEATED'}
    entry = entries[0]
    out = {'state': 'present', 'shape': 'text', 'raw': (entry.raw or b'').hex(), 'type': entry.kind}
    try:
        out['value'] = codecs.exif_text(entry, multi=d.get('editorPart', False))
        out['parts'] = 1 + (entry.raw or b'').rstrip(b'\0').count(b'\0')
    except codecs.ValueProblem as problem:
        out['undecodable'] = problem.code
    return out


READERS = {'xmp': read_xmp, 'iptc': read_iptc, 'exif': read_exif}


def read_destination(payloads, d):
    return READERS[d['family']](payloads, d)


def family_present(payloads, family):
    state = getattr(payloads, family)
    return state[0] != 'absent'


def iim_context(payloads):
    """What the capture's IPTC-IIM block allows: absent, usable with a known charset, or touchable only by deleting whole datasets."""
    state = payloads.iptc
    if state[0] == 'notApplicable':
        return {'state': 'notApplicable'}
    if state[0] == 'absent':
        return {'state': 'absent'}
    if state[0] != 'ok':
        return {'state': 'unreadable', 'code': state[2] if state[0] == 'error' else state[1], 'charset': None}
    charset = state[1]['charset']
    return {'state': 'ok' if charset != 'unsupported' else 'charsetUnsupported', 'charset': charset, 'datasets': state[1]['datasets']}


# ---------------------------------------------------------------- planning one item
def lang_map(value):
    """Expected x-default and other languages of a langText edit as ``{language: text}`` with the language compared in lower case."""
    return {'x-default': value['text'], **{e['language']: e['text'] for e in value['languages']}}


def field_value(field, edit, base):
    """The final value of a field after an edit (``None`` for clear), resolving keyword add/remove against the independently read base."""
    if 'clear' in edit:
        return None
    if 'set' in edit:
        return edit['set']
    if base is None:
        base = []
    final = list(base)
    for item in edit.get('remove', []):
        if item not in final:
            raise Refusal('EDIT_ITEM_ABSENT', 'a keyword to remove is not in the current list', '$.edits.%s.remove' % field, field=field, value=item[:60])
        final.remove(item)
    for item in edit.get('add', []):
        if item in final:
            raise Refusal('EDIT_ITEM_PRESENT', 'a keyword to add is already in the list', '$.edits.%s.add' % field, field=field, value=item[:60])
        final.append(item)
    if not final:
        raise Refusal('EDIT_EMPTY_VALUE', 'removing every keyword leaves an empty list; use clear', '$.edits.%s' % field, field=field)
    return final


def base_list(field, reads):
    """The current list of a keyword field: XMP and IPTC must not disagree (no source is preferred)."""
    values = {family: tuple(r['value']) for family, r in reads.items() if r['state'] == 'present' and 'value' in r and r.get('shape') in ('list', 'datasets')}
    for family, r in reads.items():
        if r['state'] == 'unreadable' or r.get('undecodable'):
            raise Refusal('EDIT_DESTINATION_UNREADABLE', 'a current keyword source cannot be read, so add and remove cannot be resolved', '$.edits.%s' % field, field=field, source=family, cause=r.get('code') or r.get('undecodable'))
    if len(set(values.values())) > 1:
        raise Refusal('EDIT_BASE_CONFLICT', 'the XMP and IPTC keyword lists differ, so add and remove have no single base; replace the list with set', '$.edits.%s' % field, field=field, sources={k: list(v)[:8] for k, v in values.items()})
    return list(next(iter(values.values()))) if values else []


def iptc_strings(shape, value):
    """The strings an IPTC form receives: text (the x-default of a langText) or one dataset per list item."""
    if shape == 'langText':
        return [value['text']]
    if shape in ('orderedList', 'unorderedList'):
        return list(value)
    return [value]


def exif_string(d, shape, value):
    if shape in ('orderedList', 'unorderedList'):
        return codecs.artist_join(value)
    return value['text'] if shape == 'langText' else value


def plan_field(field, edit, payloads, policies, context):
    """The destination decisions of one field: ``{'action', 'value', 'destinations': [...], 'otherLanguages', 'losses'}`` or a ``Refusal``."""
    spec = writes.fields()[field]
    shape = spec['shape']
    reads = {d['family']: read_destination(payloads, d) for d in spec['destinations']}
    at = '$.edits.' + field
    base = base_list(field, {k: v for k, v in reads.items() if k in ('xmp', 'iptc')}) if 'add' in edit or 'remove' in edit else None
    value = field_value(field, edit, base)
    action = 'clear' if value is None else 'set'
    destinations, losses = [], []
    other = {'kept': [], 'removed': []}
    for d in spec['destinations']:
        read = reads[d['family']]
        entry = {'family': d['family'], 'write': d['write'], 'listing': d['listing'], 'before': read}
        if read['state'] == 'notApplicable':            # E5: the container has no slot of this family (for example IPTC in PNG, WebP and HEIF): a declared loss, never a native warning
            entry.update(state='skip', reason='notAvailableInContainer', value=value)
            losses.append({'field': field, 'destination': d['write'], 'reason': d['family'] + 'NotAvailableInContainer', 'treatment': 'companionNotWritten'})
            destinations.append(entry)
            continue
        if d['family'] == 'xmp':
            if read['state'] == 'unreadable':
                raise Refusal('EDIT_DESTINATION_UNREADABLE', 'the current XMP value of this field cannot be read back, so it is not overwritten', at, field=field, destination=d['write'], cause=read['code'])
            if payloads.xmp[0] not in ('ok', 'absent'):
                raise Refusal('EDIT_DESTINATION_UNREADABLE', 'the XMP packet cannot be read, so it is not rewritten', at, field=field, destination=d['write'], cause=payloads.xmp[2] if payloads.xmp[0] == 'error' else payloads.xmp[1])
            if action == 'clear':
                entry['state'] = 'delete' if read['state'] == 'present' else 'skip'
                if read['state'] == 'present' and read['shape'] == 'langAlt':
                    other['removed'] = sorted(k for k in read['value'] if k != 'x-default')
            else:
                entry['state'] = 'write'
                if shape == 'langText':
                    named = {k.lower() for k in lang_map(value)}
                    existing = read['value'] if read['state'] == 'present' and read['shape'] == 'langAlt' else {'x-default': read['value']} if read['state'] == 'present' and read['shape'] == 'text' else {}
                    stray = sorted(k for k in existing if k.lower() not in named)
                    if stray and policies['otherLanguages'] == 'refuse':
                        raise Refusal('EDIT_OTHER_LANGUAGES_PRESENT', 'other languages exist that the edit does not name', at, field=field, languages=stray)
                    entry['stray'] = stray
                    other['kept' if policies['otherLanguages'] == 'keep' else 'removed'] = stray
                    entry['strayPolicy'] = policies['otherLanguages']
                    if read['state'] == 'present' and read['shape'] == 'text':
                        entry['plainBefore'] = True
            entry['value'] = value
        elif d['family'] == 'iptc':
            entry['state'] = 'pending'
            entry['value'] = value
        else:
            exif = payloads.exif
            if exif[0] == 'absent':
                entry['state'] = 'skip'
                entry['reason'] = 'noExifSegment'
            elif exif[0] != 'ok' or read['state'] == 'unreadable':
                raise Refusal('EDIT_DESTINATION_UNREADABLE', 'the current EXIF value of this field cannot be read back, so it is not overwritten', at, field=field, destination=d['write'], cause=read.get('code') or (exif[2] if exif[0] == 'error' else exif[1]))
            elif action == 'clear':
                entry['state'] = 'delete' if read['state'] == 'present' else 'skip'
            else:
                entry['state'] = 'write'
                entry['string'] = exif_string(d, shape, value)
                reason = None
                if d.get('editorPart') and read['state'] == 'present' and read.get('parts', 1) > 1:
                    reason = 'exifCopyrightEditorPart'
                elif policies['exifEncoding'] == 'ascii' and not ascii_text(entry['string']):
                    reason = 'exifNonAscii'
                if reason:
                    if policies['companionLoss'] == 'refuse':
                        raise Refusal('COMPANION_LOSS_REFUSED', 'the EXIF form cannot hold this value exactly and the loss policy refuses', at, field=field, destination=d['write'], reason=reason)
                    entry['state'] = 'delete' if read['state'] == 'present' else 'skip'
                    entry['reason'] = reason
                    entry.pop('string')
                    losses.append({'field': field, 'destination': d['write'], 'reason': reason, 'treatment': 'companionRemoved' if read['state'] == 'present' else 'companionNotWritten'})
            entry['value'] = value
        destinations.append(entry)
    if destinations and all(d.get('reason') == 'notAvailableInContainer' for d in destinations):
        raise Refusal('FIELD_NOT_WRITABLE_IN_CONTAINER', 'no destination of this field exists in this container', at, field=field)
    return {'field': field, 'shape': shape, 'action': action, 'edit': edit, 'value': value, 'destinations': destinations, 'otherLanguages': other, 'losses': losses}


def plan_iptc(fields, payloads, policies):
    """Item-level IPTC decisions: which datasets are written or deleted, whether 1:90 is assigned, and the loss of unwritable forms."""
    context = iim_context(payloads)
    wanted = {name: next(d for d in plan['destinations'] if d['family'] == 'iptc') for name, plan in fields.items() if any(d['family'] == 'iptc' and d['state'] == 'pending' for d in plan['destinations'])}
    written_sets, assign = set(), False
    for name, entry in wanted.items():
        plan, spec = fields[name], writes.fields()[name]
        d = next(x for x in spec['destinations'] if x['family'] == 'iptc')
        read = entry['before']
        if read['state'] == 'unreadable':
            raise Refusal('EDIT_DESTINATION_UNREADABLE', 'the current IPTC value of this field cannot be read back, so it is not overwritten', '$.edits.' + name, field=name, destination=d['write'], cause=read['code'])
        if read.get('undecodable') and policies['companionLoss'] == 'refuse':
            raise Refusal('IPTC_EXISTING_CHARSET_UNKNOWN', 'the current IPTC text has no known character set and the loss policy refuses', '$.edits.' + name, field=name, cause=read['undecodable'])
        if plan['action'] == 'clear':
            entry['state'] = 'delete' if read['state'] == 'present' and context['state'] != 'unreadable' else 'skip'
            if context['state'] == 'unreadable' and read['state'] == 'present':
                raise Refusal('EDIT_DESTINATION_UNREADABLE', 'the IPTC block cannot be read, so its datasets are not deleted', '$.edits.' + name, field=name, cause=context['code'])
            if entry['state'] == 'delete':
                written_sets.add((d['record'], d['dataset']))
            continue
        strings = iptc_strings(plan['shape'], plan['value'])
        limit = d.get('itemMaxBytes', d.get('maxBytes'))
        over = [len(s.encode('utf-8')) for s in strings if len(s.encode('utf-8')) > limit]
        reason = None
        if context['state'] == 'absent' and policies['iptc'] == 'ifPresent':
            entry['state'], entry['reason'] = 'skip', 'noIptcBlock'
            continue
        if context['state'] == 'unreadable':
            raise Refusal('EDIT_DESTINATION_UNREADABLE', 'the IPTC block cannot be read, so it is not rewritten', '$.edits.' + name, field=name, cause=context['code'])
        if over:
            reason = 'iptcLength'
        elif context['state'] == 'charsetUnsupported':
            reason = 'iptcCharsetUnsupported'
        entry['strings'] = strings
        entry['bytes'] = [len(s.encode('utf-8')) for s in strings]
        entry['state'] = 'write'
        if reason:
            entry.update(state='lost', reason=reason, limit=limit, over=over)
        elif not all(ascii_text(s) for s in strings):
            entry['nonAscii'] = True
        written_sets.add((d['record'], d['dataset']))
    # character set: a non-ASCII value needs UTF-8 declared; that is only safe when no untouched dataset would be reinterpreted by it
    needs_utf8 = any(e['state'] == 'write' and e.get('nonAscii') for e in wanted.values())
    if needs_utf8 and context['state'] == 'ok' and context['charset'] == 'unspecified':
        untouched = [(k, v) for k, v in context['datasets'].items() if charset_scoped(k) and k not in written_sets and any(not ascii_text(b.decode('latin-1')) for b in v)]
        if untouched:
            for name, e in wanted.items():
                if e['state'] == 'write' and e.get('nonAscii'):
                    e.update(state='lost', reason='iptcCharsetUnknown', untouched=sorted('%d:%d' % k for k, _ in untouched)[:8])
        else:
            assign = True
    elif needs_utf8 and context['state'] == 'absent':
        assign = True
    for name, e in wanted.items():
        if e['state'] == 'lost':
            if policies['companionLoss'] == 'refuse':
                raise Refusal('COMPANION_LOSS_REFUSED', 'the IPTC form cannot hold this value exactly and the loss policy refuses', '$.edits.' + name, field=name, destination=e['write'], reason=e['reason'])
            present = e['before']['state'] == 'present'
            e['state'] = 'delete' if present else 'skip'
            fields[name]['losses'].append({'field': name, 'destination': e['write'], 'reason': e['reason'], 'treatment': 'companionRemoved' if present else 'companionNotWritten',
                                           **({'limit': e['limit'], 'bytes': e['over']} if e['reason'] == 'iptcLength' else {}), **({'untouched': e['untouched']} if 'untouched' in e else {})})
            e.pop('strings', None)
    changed = any(e['state'] in ('write', 'delete') for e in wanted.values())
    created = changed and context['state'] == 'absent'
    return {'state': context['state'], 'charset': context.get('charset'), 'assignCharset': assign and changed, 'changed': changed, 'created': created}


def plan_item(item_edits, payloads, policies, digest_before=False):
    """The complete plan of one item, or a ``Refusal``."""
    fields = {}
    for name in writes.fields():
        if name in item_edits:
            fields[name] = plan_field(name, item_edits[name], payloads, policies, None)
    iptc = plan_iptc(fields, payloads, policies)
    xmp_writes = any(d['family'] == 'xmp' and d['state'] in ('write', 'delete') for f in fields.values() for d in f['destinations'])
    xmp_after = payloads.xmp[0] != 'absent' or any(d['family'] == 'xmp' and d['state'] == 'write' for f in fields.values() for d in f['destinations'])
    iptc['digest'] = bool(iptc['changed'] and (xmp_after or digest_before))
    declared = {'xmp': xmp_writes, 'iptc': iptc['changed'], 'exif': any(d['family'] == 'exif' and d['state'] in ('write', 'delete') for f in fields.values() for d in f['destinations'])}
    return {'fields': fields, 'iptc': iptc, 'declared': declared, 'xmpWritten': xmp_writes}


# ---------------------------------------------------------------- native assignments
def assignments(plan):
    """The ordered native argument list of one item plan; every argument is ``-<catalogue write name>=<value>`` and nothing else."""
    args = []
    iptc = plan['iptc']
    if iptc['assignCharset']:
        args.append('-IPTC:CodedCharacterSet=UTF8')
    for name, f in plan['fields'].items():
        for d in f['destinations']:
            tag = d['write']
            state = d['state']
            if state not in ('write', 'delete'):
                continue
            if d['family'] == 'xmp':
                if state == 'delete':
                    args.append('-%s=' % tag)
                    continue
                if f['shape'] == 'langText':
                    args.append('-%s-x-default=%s' % (tag, f['value']['text']))
                    args += ['-%s-%s=%s' % (tag, e['language'], e['text']) for e in f['value']['languages']]
                    if d['strayPolicy'] == 'remove':
                        args += ['-%s-%s=' % (tag, lang) for lang in d['stray']]
                elif f['shape'] in ('orderedList', 'unorderedList'):
                    args += ['-%s=%s' % (tag, item) for item in f['value']]
                else:
                    args.append('-%s=%s' % (tag, f['value']))
            elif d['family'] == 'iptc':
                if state == 'delete':
                    args.append('-%s=' % tag)
                else:
                    args += ['-%s=%s' % (tag, s) for s in d['strings']]
            else:
                args.append('-%s=' % tag if state == 'delete' else '-%s=%s' % (tag, d['string']))
    if iptc['digest']:
        args.append('-Photoshop:IPTCDigest=new')
    return args
