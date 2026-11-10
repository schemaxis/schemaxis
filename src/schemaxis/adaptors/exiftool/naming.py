"""File and folder naming of ``planNames`` and ``organiseCopies`` (host-only, standard library, no native import).

A rule is a closed list of domain tokens (capture date and time, camera text, the original stem, the item id, a sequence number) and literals; there is no
template language, no expression, no date arithmetic and no regular expression. The planner turns the typed capture facts of each item into a candidate
relative path, sanitises every component, resolves collisions over the whole output set (images, adjacent sidecars and directories together) and publishes
one deterministic plan document. The sanitiser is declared, never silent: every replacement, truncation and normalisation is listed per item.

Times are exact integer arithmetic over the recorded wall time and recorded offset (``timecalc``); no system time zone, file modification time or
locale is ever consulted.
"""
import hashlib
import json
import unicodedata

from schemaxis.adaptors.exiftool import e5profiles, timecalc as tc

VERSION = 'schemaxis.exiftool.name-plan/1'
RULE_VERSION = 'schemaxis.exiftool.name-rule/1'
DATE_FORMATS = ('YYYYMMDD', 'YYYY-MM-DD')
TIME_FORMATS = ('HHmmss', 'HH-mm-ss', 'HHmmssSSS')
TEXT_TOKENS = ('cameraMake', 'cameraModel', 'originalStem', 'itemId')
FOLDER_TOKENS = ('year', 'month', 'day', 'captureDate', 'cameraModel', 'cameraMake')
NAME_TOKENS = ('captureDate', 'captureTime', *TEXT_TOKENS, 'sequence')
SCOPES = ('global', 'perFolder', 'perName')
BASES = ('recordedLocal', 'utc')
SOURCES = ('concordantOnly', 'exif', 'xmp', 'iptc')
MAX_PARTS, MAX_LEVELS = 12, 4
MAX_COMPONENT_BYTES, MAX_PATH_BYTES, MAX_COMPONENTS = 120, 1024, 5
MAX_LITERAL = 40
RESERVED = {'CON', 'PRN', 'AUX', 'NUL'} | {'COM%d' % i for i in range(1, 10)} | {'LPT%d' % i for i in range(1, 10)} | {'COM¹', 'COM²', 'COM³', 'LPT¹', 'LPT²', 'LPT³'}
REPLACED = set('/\\:*?"<>|\0')
BIDI = set(range(0x202A, 0x202F)) | set(range(0x2066, 0x206A))
EXTENSIONS = {'jpeg': ('.jpg', ('.jpg', '.jpeg')), 'tiff': ('.tif', ('.tif', '.tiff')), 'dng': ('.dng', ('.dng',)), 'png': ('.png', ('.png',)), 'webp': ('.webp', ('.webp',)),
              'heic': ('.heic', ('.heic', '.heif')), 'heif': ('.heic', ('.heic', '.heif', '.avif')), 'xmp': ('.xmp', ('.xmp',))}      # E5: the HEIF locator's container id is 'heif'; its canonical extension follows the located brand (an AVIF is .avif, see extension_of)


class NamingError(ValueError):
    """An authored rule problem (the caller turns it into a schemaxis fault)."""

    def __init__(self, code, message, location, **observed):
        super().__init__(message)
        self.code, self.message, self.location, self.observed = code, message, location, observed


def bad(message, location, **observed):
    raise NamingError('INVALID_NAME_RULE', message, location, **observed)


# ---------------------------------------------------------------- the rule
def part(entry, at, allowed, folder=False):
    if not isinstance(entry, dict):
        bad('a rule part is an object', at)
    if 'literal' in entry:
        if set(entry) != {'literal'}:
            bad('a literal part has only literal', at)
        text = entry['literal']
        if not isinstance(text, str) or not text or len(text) > MAX_LITERAL:
            bad('a literal is 1 to %d characters' % MAX_LITERAL, at + '.literal')
        return {'literal': text}
    token = entry.get('token')
    if token not in allowed:
        bad('token must be one of ' + ', '.join(allowed), at + '.token', value=str(token)[:40])
    extra = set(entry) - {'token'}
    out = {'token': token}
    if token == 'captureDate':
        extra -= {'format'}
        out['format'] = entry.get('format', 'YYYYMMDD')
        if out['format'] not in DATE_FORMATS:
            bad('format must be one of ' + ', '.join(DATE_FORMATS), at + '.format')
    elif token == 'captureTime':
        extra -= {'format'}
        out['format'] = entry.get('format', 'HHmmss')
        if out['format'] not in TIME_FORMATS:
            bad('format must be one of ' + ', '.join(TIME_FORMATS), at + '.format')
    elif token == 'sequence':
        extra -= {'width', 'start', 'scope'}
        out.update(width=entry.get('width', 3), start=entry.get('start', 1), scope=entry.get('scope', 'global'))
        if type(out['width']) is not int or not 1 <= out['width'] <= 6:
            bad('width is 1 to 6', at + '.width')
        if type(out['start']) is not int or not 0 <= out['start'] <= 999999:
            bad('start is 0 to 999999', at + '.start')
        if out['scope'] not in SCOPES:
            bad('scope must be one of ' + ', '.join(SCOPES), at + '.scope')
    if extra:
        bad('unsupported keys for token ' + token, at, keys=sorted(extra))
    return out


def normalise_rule(rule):
    """The closed, fully defaulted rule: ``name`` parts, ``folders``, ``time``, ``text``, ``collisions`` and ``extension``."""
    parts = rule.get('name')
    if not isinstance(parts, list) or not 1 <= len(parts) <= MAX_PARTS:
        bad('name is a list of 1 to %d parts' % MAX_PARTS, '$.names.name')
    name = [part(e, '$.names.name[%d]' % i, NAME_TOKENS) for i, e in enumerate(parts)]
    if not any('token' in e for e in name):
        bad('the name needs at least one token: a literal alone names every file alike', '$.names.name')
    folders = rule.get('folders', 'flat')
    if folders != 'flat':
        if not isinstance(folders, list) or len(folders) > MAX_LEVELS:
            bad('folders is "flat" or a list of at most %d levels' % MAX_LEVELS, '$.names.folders')
        folders = [part(e, '$.names.folders[%d]' % i, FOLDER_TOKENS, True) for i, e in enumerate(folders)] or 'flat'
    time = dict(rule.get('time') or {})
    unknown = set(time) - {'basis', 'source', 'missing', 'missingOffset'}
    if unknown:
        bad('unsupported time keys', '$.names.time', keys=sorted(unknown))
    basis = time.get('basis', 'recordedLocal')
    if isinstance(basis, dict):
        if set(basis) != {'fixedOffset'} or not isinstance(basis['fixedOffset'], str):
            bad('a fixed offset basis is {"fixedOffset": "+HH:MM"}', '$.names.time.basis')
        try:
            tc.parse_offset(basis['fixedOffset'])
        except tc.TimeProblem as error:
            bad(error.message, '$.names.time.basis.fixedOffset', value=basis['fixedOffset'][:12])
        basis = {'fixedOffset': basis['fixedOffset']}
    elif basis not in BASES:
        bad('basis must be recordedLocal, utc or {"fixedOffset": "+HH:MM"}', '$.names.time.basis')
    source = time.get('source', 'concordantOnly')
    if source not in SOURCES:
        bad('source must be one of ' + ', '.join(SOURCES), '$.names.time.source')
    missing = time.get('missing', 'refuseItem')
    if missing != 'refuseItem':
        if not isinstance(missing, dict) or set(missing) != {'fallback'}:
            bad('missing is "refuseItem" or {"fallback": "text"}', '$.names.time.missing')
        missing = {'fallback': fallback_text(missing['fallback'], '$.names.time.missing.fallback')}
    missing_offset = time.get('missingOffset', 'refuseItem')
    if missing_offset not in ('refuseItem', 'useRecordedLocal'):
        bad('missingOffset is refuseItem or useRecordedLocal', '$.names.time.missingOffset')
    text = dict(rule.get('text') or {})
    if set(text) - {'missing'}:
        bad('unsupported text keys', '$.names.text', keys=sorted(set(text) - {'missing'}))
    text_missing = text.get('missing', 'refuseItem')
    if text_missing != 'refuseItem':
        if not isinstance(text_missing, dict) or set(text_missing) != {'fallback'}:
            bad('missing is "refuseItem" or {"fallback": "text"}', '$.names.text.missing')
        text_missing = {'fallback': fallback_text(text_missing['fallback'], '$.names.text.missing.fallback')}
    collisions = rule.get('collisions', 'refuse')
    if collisions not in ('refuse', 'sequence'):
        bad('collisions is refuse or sequence', '$.names.collisions')
    extension = rule.get('extension', 'canonical')
    if extension not in ('canonical', 'keepOriginal'):
        bad('extension is canonical or keepOriginal', '$.names.extension')
    return {'version': RULE_VERSION, 'name': name, 'folders': folders, 'time': {'basis': basis, 'source': source, 'missing': missing, 'missingOffset': missing_offset},
            'text': {'missing': text_missing}, 'collisions': collisions, 'extension': extension}


def fallback_text(text, at):
    if not isinstance(text, str) or not text or len(text) > 60:
        bad('a fallback is 1 to 60 characters', at)
    return text


# ---------------------------------------------------------------- the sanitiser
def clean(text, notes, where, keep_dots=False):
    """NFC, control and bidi replacement, forbidden-character replacement with collapsed runs, edge stripping. ``notes`` collects declared changes."""
    nfc = unicodedata.normalize('NFC', text)
    if nfc != text:
        notes.append({'code': 'nfcNormalised', 'component': where})
    out, count, last_replacement = [], 0, False
    for c in nfc:
        code = ord(c)
        replace = c in REPLACED or code < 32 or 0x7F <= code <= 0x9F or code in (0x2028, 0x2029, 0xFEFF) or code in BIDI or 0xD800 <= code <= 0xDFFF
        if replace:
            count += 1
            if not last_replacement:
                out.append('_')
            last_replacement = True
        else:
            out.append(c)
            last_replacement = False
    if count:
        notes.append({'code': 'replacedCharacters', 'component': where, 'count': count})
    value = ''.join(out)
    stripped = value.strip(' ') if keep_dots else value.strip(' .')
    if stripped != value:
        notes.append({'code': 'strippedEdges', 'component': where})
    return stripped


def utf8_truncate(text, limit):
    data = text.encode('utf-8')
    if len(data) <= limit:
        return text, False
    return data[:limit].decode('utf-8', 'ignore'), True


def guard_stem(stem, notes, where):
    """Reserved device names (case-insensitive, with or without extension) receive a trailing underscore; a leading hyphen is replaced."""
    head = stem.split('.', 1)[0].rstrip(' ')
    if unicodedata.normalize('NFC', head).upper() in RESERVED:
        notes.append({'code': 'reservedName', 'component': where, 'name': head})
        stem = head + '_' + stem[len(head):]
    if stem.startswith('-'):
        notes.append({'code': 'leadingHyphen', 'component': where})
        stem = '_' + stem[1:]
    return stem


def component(text, notes, where, extension='', missing=None):
    """One sanitised path component (``extension`` is appended after the stem is limited so that the whole stays within the byte bound)."""
    value = clean(text, notes, where)
    if value in ('', '.', '..'):
        return None
    value = guard_stem(value, notes, where)
    room = MAX_COMPONENT_BYTES - len(extension.encode('utf-8'))
    value, cut = utf8_truncate(value, room)
    if cut:
        notes.append({'code': 'truncated', 'component': where, 'limitBytes': MAX_COMPONENT_BYTES})
        value = value.rstrip(' .')
    return value + extension if value else None


def collision_key(text):
    return unicodedata.normalize('NFC', text).casefold()


# ---------------------------------------------------------------- capture time
def wall_of(local, fraction):
    """Wall nanoseconds of a canonical local time (``YYYY-MM-DDTHH:MM:SS``) and recorded sub-second digits (or ``None``)."""
    match = tc.LOCAL.fullmatch(local + ('.' + fraction if fraction else ''))
    if not match:
        raise tc.TimeProblem('INVALID_DATE_VALUE', 'not a canonical local time')
    y, mo, d, h, mi, s = (int(x) for x in match.groups()[:6])
    ns = int((match.group(7) or '').ljust(9, '0')) if match.group(7) else 0
    return tc.from_parts(y, mo, d, h, mi, s, ns)


def resolve_time(rule, subject, uses_millis=False):
    """``(parts, notes)`` of the capture time of one item under the rule, or a ``(code, message, observed)`` refusal tuple as the first element's replacement."""
    spec = rule['time']
    sources = subject['time']
    chosen = sources['aggregate'] if spec['source'] == 'concordantOnly' else sources[spec['source']]
    notes = []
    if spec['source'] != 'concordantOnly':
        agg = sources['aggregate']
        if agg['state'] == 'ambiguous':
            notes.append({'code': 'NAME_TIME_SOURCES_DISAGREE', 'severity': 'info', 'values': agg.get('values', [])})
    state = chosen['state']
    if state == 'ambiguous':
        return None, [], ('NAME_TIME_CONFLICT', 'the recorded capture-time sources disagree, so no single time names this file; reconcile or choose a source family', {'values': chosen.get('values', [])})
    if state != 'present':
        if state == 'absent' and spec['missing'] != 'refuseItem':
            return {'fallback': spec['missing']['fallback']}, [{'code': 'timeFallback', 'text': spec['missing']['fallback']}], None
        return None, [], ('NAME_TIME_MISSING', 'the item records no usable capture time' if state == 'absent' else 'the capture time exists but cannot be read, so it is never treated as absent',
                          {'state': state, 'source': spec['source']})
    unanchored = [c for c in chosen.get('unanchored', []) if c['component'] == 'sub' or spec['basis'] != 'recordedLocal']
    if unanchored:         # the offset (for a UTC or fixed-offset basis) and the fraction (always, it orders the names) must belong to the time they are combined with
        from schemaxis.adaptors.exiftool import e4model
        message, observed = e4model.unanchored_problem(unanchored, 'source')
        return None, [], ('NAME_TIME_COMPONENT_UNANCHORED', message, {k: v for k, v in observed.items() if k != 'side'})
    local, offset = chosen['local'], chosen.get('offset')
    try:
        wall = wall_of(local, None)
        sub_state, sub = chosen.get('subState', 'absent'), chosen.get('sub')
        if sub_state in ('unreadable', 'ambiguous', 'unsupported'):
            sub = None
        basis = spec['basis']
        if basis == 'recordedLocal':
            shown = wall
        else:
            if offset is None:
                if spec['missingOffset'] == 'useRecordedLocal':
                    shown = wall
                    notes.append({'code': 'offsetMissingUsedLocal'})
                else:
                    return None, [], ('NAME_OFFSET_MISSING', 'the item records no UTC offset, so its capture time cannot be converted', {'basis': basis if isinstance(basis, str) else 'fixedOffset'})
            else:
                instant = wall - tc.parse_offset(offset) * 60 * tc.NS
                shown = instant if basis == 'utc' else instant + tc.parse_offset(basis['fixedOffset']) * 60 * tc.NS
        y, mo, d, h, mi, s, ns = tc.parts(shown)
    except tc.TimeProblem as error:
        return None, [], ('NAME_TIME_MISSING', 'the capture time is outside the supported calendar: ' + error.message, {'code': error.code})
    millis = None
    if sub_state in ('unreadable', 'ambiguous', 'unsupported'):
        millis = ('unreadable', None)
    elif sub:
        millis = ('ok', sub[:3].ljust(3, '0'))
        if uses_millis and len(sub) != 3:
            notes.append({'code': 'subSecondAdjusted', 'recorded': sub, 'written': millis[1]})
    else:
        millis = ('absent', '000')
    return {'y': y, 'mo': mo, 'd': d, 'h': h, 'mi': mi, 's': s, 'millis': millis, 'sortKey': shown + (int(sub.ljust(9, '0')) if sub else 0)}, notes, None


def date_text(parts, fmt):
    return ('%04d%02d%02d' if fmt == 'YYYYMMDD' else '%04d-%02d-%02d') % (parts['y'], parts['mo'], parts['d'])


def time_text(parts, fmt):
    if fmt == 'HH-mm-ss':
        return '%02d-%02d-%02d' % (parts['h'], parts['mi'], parts['s'])
    text = '%02d%02d%02d' % (parts['h'], parts['mi'], parts['s'])
    if fmt == 'HHmmssSSS':
        if parts['millis'][0] == 'unreadable':
            raise NamingError('NAME_TIME_MISSING', 'the sub-second digits exist but cannot be read, so they are never replaced by 000', '$.names.name', state='unreadable')
        text += parts['millis'][1]
    return text


# ---------------------------------------------------------------- one item
def text_value(rule, subject, token):
    if token == 'originalStem':
        return subject['stem'], None
    if token == 'itemId':
        return subject['id'], None
    field = subject[token]
    if field['state'] == 'present' and field.get('value'):
        return field['value'], None
    return None, field['state']


def render(rule, subject, parts_, time, notes, folder=False):
    """The text of one rule part list for one item; returns ``(text, refusal)``."""
    out = []
    for entry in parts_:
        if 'literal' in entry:
            out.append(entry['literal'])
            continue
        token = entry['token']
        if token in ('captureDate', 'captureTime', 'year', 'month', 'day'):
            if 'fallback' in time:
                out.append(time['fallback'])
                continue
            try:
                if token == 'captureDate':
                    out.append(date_text(time, entry['format']))
                elif token == 'captureTime':
                    out.append(time_text(time, entry['format']))
                else:
                    out.append({'year': '%04d' % time['y'], 'month': '%02d' % time['mo'], 'day': '%02d' % time['d']}[token])
            except NamingError as error:
                return None, (error.code, error.message, error.observed)
        elif token == 'sequence':
            out.append('\0SEQ\0')
        else:
            value, state = text_value(rule, subject, token)
            if value is None:
                missing = rule['text']['missing']
                if state in ('present', 'absent') and missing != 'refuseItem':
                    value = missing['fallback']
                    notes.append({'code': 'textFallback', 'token': token, 'text': value})
                else:
                    return None, ('NAME_TEXT_MISSING', 'the item records no %s%s' % (token, '' if state == 'absent' else ' that can be read (state ' + str(state) + ')'), {'token': token, 'state': state})
            out.append(value)
    return ''.join(out), None


def candidate(rule, subject, index):
    """The candidate of one item before collisions: ``{'folders': [...], 'stem': text with sequence marks, 'notes': [...], 'sortKey': ...}`` or a refusal."""
    notes = []
    uses_millis = any(e.get('format') == 'HHmmssSSS' for e in rule['name'])
    time, time_notes, refusal = resolve_time(rule, subject, uses_millis)
    if refusal and any(isinstance(e, dict) and e.get('token') in ('captureDate', 'captureTime', 'year', 'month', 'day') for e in rule['name'] + (rule['folders'] if rule['folders'] != 'flat' else [])):
        return {'refusal': refusal}
    if refusal:
        time, time_notes = {'fallback': ''}, []
    notes += time_notes
    folders = []
    if rule['folders'] != 'flat':
        for level, entry in enumerate(rule['folders']):
            text, refusal = render(rule, subject, [entry], time, notes, True)
            if refusal:
                return {'refusal': refusal}
            folders.append(component(text, notes, 'folder%d' % (level + 1), missing=None) if text is not None else None)
            if folders[-1] is None:
                fallback = rule['text']['missing']
                if fallback == 'refuseItem':
                    return {'refusal': ('NAME_PATH_UNSAFE', 'a folder component is empty after sanitising', {'level': level + 1})}
                folders[-1] = component(fallback['fallback'], notes, 'folder%d' % (level + 1))
                notes.append({'code': 'textFallback', 'component': 'folder%d' % (level + 1)})
                if folders[-1] is None:
                    return {'refusal': ('NAME_PATH_UNSAFE', 'a folder component is empty after sanitising', {'level': level + 1})}
    stem, refusal = render(rule, subject, rule['name'], time, notes)
    if refusal:
        return {'refusal': refusal}
    return {'folders': folders, 'stem': stem, 'notes': notes, 'sortKey': time.get('sortKey') if isinstance(time, dict) else None}


def sequence_text(entry, number):
    return str(number).rjust(entry['width'], '0')


def sequence_entry(rule):
    return next((e for e in rule['name'] if e.get('token') == 'sequence'), None)


# ---------------------------------------------------------------- the plan
def extension_of(rule, subject):
    canonical, accepted = EXTENSIONS[subject['container']]
    if subject['container'] == 'heif':
        canonical = e5profiles.extension({'container': 'heif', 'brand': subject.get('brand')})       # one rule with the capture's own extension: an AVIF keeps '.avif', a HEIC is '.heic'
    original = subject['suffix'].lower()
    info = None
    if original not in accepted:
        info = {'code': 'EXTENSION_MISMATCH', 'severity': 'info', 'suffix': original, 'container': subject['container']}
    return (canonical if rule['extension'] == 'canonical' else original or canonical), info


def plan(rule, subjects):
    """The deterministic name plan of ``subjects`` (manifest order) under a normalised ``rule``; every item is planned or refused with a stable code."""
    rule_json = json.dumps(rule, sort_keys=True)
    items = []
    for index, subject in enumerate(subjects):
        row = {'id': subject['id'], 'order': subject['order'], 'status': 'planned', 'fault': None, 'notes': [], 'relativePath': None, 'sidecarPath': None, 'sidecar': bool(subject.get('sidecar'))}
        items.append(row)
        found = candidate(rule, subject, index)
        if 'refusal' in found:
            code, message, observed = found['refusal']
            row.update(status='refused', fault={'code': code, 'message': message, 'location': subject['id'], **observed})
            continue
        row['_c'] = found
        row['_subject'] = subject
    planned = [r for r in items if r['status'] == 'planned']
    seq = sequence_entry(rule)
    # sequence numbers: assigned in a deterministic order (name without sequence, capture instant, manifest order) and recorded in the plan
    ordering = {}
    if seq is not None:
        def base(r): return (r['_c']['stem'].replace('\0SEQ\0', ''), '/'.join(r['_c']['folders']))
        ranked = sorted(planned, key=lambda r: (base(r)[0], r['_c']['sortKey'] if r['_c']['sortKey'] is not None else -1, r['order']))
        counters, group_sizes = {}, {}
        for r in planned:
            group_sizes[base(r)] = group_sizes.get(base(r), 0) + 1
        for r in ranked:
            scope = seq['scope']
            key = None if scope == 'global' else base(r)[1] if scope == 'perFolder' else base(r)
            if scope == 'perName' and group_sizes[base(r)] == 1:
                ordering[r['id']] = ''
                r['notes'].append({'code': 'sequenceOmittedUnique'})
                continue
            number = counters.get(key, seq['start'])
            counters[key] = number + 1
            if number > 10 ** seq['width'] - 1:
                row_fault = {'code': 'NAME_PATH_UNSAFE', 'message': 'the sequence number does not fit the declared width', 'location': r['id'], 'width': seq['width']}
                r.update(status='refused', fault=row_fault)
                continue
            ordering[r['id']] = sequence_text(seq, number)
    for r in planned:
        if r['status'] != 'planned':
            continue
        c, subject = r['_c'], r['_subject']
        notes = r['notes'] + c['notes']
        stem = c['stem'].replace('\0SEQ\0', ordering.get(r['id'], ''))
        extension, info = extension_of(rule, subject)
        if info:
            notes.append(info)
        name = component(stem, notes, 'name', extension)
        if name is None:
            fallback = rule['text']['missing']
            if fallback == 'refuseItem':
                r.update(status='refused', fault={'code': 'NAME_PATH_UNSAFE', 'message': 'the file name is empty after sanitising', 'location': r['id']})
                continue
            name = component(fallback['fallback'], notes, 'name', extension)
        parts_ = list(c['folders']) + [name]
        path = '/'.join(parts_)
        if len(parts_) > MAX_COMPONENTS or len(path.encode('utf-8')) > MAX_PATH_BYTES:
            r.update(status='refused', fault={'code': 'NAME_PATH_UNSAFE', 'message': 'the relative path exceeds %d components or %d bytes' % (MAX_COMPONENTS, MAX_PATH_BYTES), 'location': r['id']})
            continue
        r.update(relativePath=path, notes=notes)
    collide(rule, items)
    for r in items:
        for key in ('_c', '_subject'):
            r.pop(key, None)
        if r['status'] == 'planned' and r['sidecar']:
            stem, dot, _ = r['relativePath'].rpartition('.')
            r['sidecarPath'] = stem + '.xmp'
    return {'version': VERSION, 'rule': rule, 'ruleSha256': hashlib.sha256(rule_json.encode()).hexdigest(), 'items': items}


def unit_key(path, with_sidecars):
    """The collision unit: the casefolded NFC path; when sidecars are carried, the stem within its folder (an image and its sidecar are one unit)."""
    folder, _, name = path.rpartition('/')
    stem = name.rpartition('.')[0] if with_sidecars else name
    return collision_key((folder + '/' if folder else '') + stem)


def collide(rule, items):
    """Resolve or refuse collisions over files, adjacent sidecars and directories (a file ``a`` and a directory ``A`` collide)."""
    with_sidecars = any(r['sidecar'] for r in items if r['status'] == 'planned')
    for _ in range(len(items) + 2):
        groups = {}
        directories = {}
        for r in items:
            if r['status'] != 'planned':
                continue
            groups.setdefault(unit_key(r['relativePath'], with_sidecars), []).append(r)
            parts_ = r['relativePath'].split('/')
            for depth in range(1, len(parts_)):
                directories.setdefault(collision_key('/'.join(parts_[:depth])), set()).add('/'.join(parts_[:depth]))
        found = False
        for key, members in groups.items():
            clash = len(members) > 1 or key in directories
            if not clash:
                continue
            found = True
            if rule['collisions'] == 'refuse':
                names = [m['relativePath'] for m in members]
                for m in members:
                    m.update(status='refused', fault={'code': 'NAME_COLLISION', 'message': 'two outputs share one case- and normalisation-insensitive name', 'location': m['id'],
                                                      'members': sorted(names)[:20], 'items': sorted(x['id'] for x in members)[:20]})
                    m['relativePath'] = None
            else:
                ordered = sorted(members, key=lambda m: m['order'])
                keep = 0 if key not in directories else -1
                for number, m in enumerate(ordered[keep + 1:] if keep == 0 else ordered, 2):
                    folder, _, name = m['relativePath'].rpartition('/')
                    stem, dot, extension = name.rpartition('.')
                    base = stem or name
                    suffix = '-%d' % number
                    room = MAX_COMPONENT_BYTES - len(('.' + extension).encode('utf-8') if dot else b'') - len(suffix)
                    base, _ = utf8_truncate(base, room)
                    m['relativePath'] = (folder + '/' if folder else '') + base + suffix + ('.' + extension if dot else '')
                    m['notes'].append({'code': 'collisionSequence', 'number': number})
        if not found:
            return
    raise NamingError('NAME_COLLISION', 'collision resolution did not converge', '$.names')
