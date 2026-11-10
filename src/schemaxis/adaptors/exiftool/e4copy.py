"""Typed transfer of selected metadata onto copies of JPEG photos: ``copyMetadata`` and ``applySidecar`` (host planner over the shared E2 copy writer).

The destination receives *values*: the independently decoded, natively anchored typed facts of a source snapshot (another item of the run, one captured file, or
the item's XMP sidecar), re-encoded by the unchanged E2 copy writer (one ExifTool process per item, ``-o`` to a private stage) and read back independently. Nothing
here runs ``-tagsFromFile`` or copies a block, MakerNote or unknown tag; the losses say so. There is no second writer: the plan is the E2 edit plan of the
descriptive, rights, rating and place fields plus a small pinned table of EXIF destinations for camera, lens, serial and exposure values (exact numerator/denominator
pairs), and the proofs are the E2 proofs R, P and N plus proof T:

* T-host: the raw decoded literal of each transferred field (exact text, language set, list order, rational pair, captured local time, offset and fraction) of the source capture equals that of the
  output, a position equals the source's within the declared nine-decimal half-even quantisation with its typed altitude and datum, and every kept, skipped or cleared field matches its plan decision;
* T-native: wherever the fixed ExifTool listing of the source capture and of the output carry the same key, the tokens are identical (a captured time and a position are compared as the typed values the listings state;
  a captured time is one time composed, component by component, from the carriers of the listing that state it: Exif DateTimeOriginal with its OffsetTimeOriginal and SubSecTimeOriginal, XMP exif, XMP photoshop,
  and the IPTC date 2:55 with its time 2:60, in the source listing and in the output listing alike; an offset or fraction that a carrier states without that carrier's own local time is no part of the listing's
  time, and the host planner refuses such a source before any write, see ``e4model.unanchored``), so a reader that normalises both sides cannot make a changed value look equal.

Every item, whether it selects one group or a union, is one ``transfer`` plan evaluated by ``evaluate`` below, so proof T always runs; the untouched-data guards use the union of every part's declared targets.

A transfer never creates an Exif block or an ExifIFD: the native writer would add mandatory values (such as ExifVersion) that change what an untouched GPS-only height means.
Such an item is refused with a precise code, and the typed height is read again after every write.
"""
import hashlib
import json
import re
from fractions import Fraction
from importlib.resources import files
from pathlib import Path

from schemaxis.adaptors.exiftool import adaptor as legacy, catalogue, containers, e3proofs, e3writes, e4model, e5edit, e5proof, edits, jpegwrite, listing, mediaset, proofs, records, writes

OPERATIONS = ('copyMetadata', 'applySidecar')
VERSION = 'schemaxis.exiftool.writes/2'
FILE = 'writes-4.json'
PIN = '5e6a9390d1b2a2c87b86bc5282fb99c4baaa650e8026fbf84886f397b2353695'
PLAN_SCHEMA = 'schemaxis.exiftool.transfer.plan/1'
PLAN_FILE = 'transfer-plan.json'
REPORT_FILE = 'transfer-report.json'
VIEW = catalogue.VERSION_E4
INPUTS = 'inputs'
POLICY_DEFAULTS = {'existing': 'refuseConflict', 'absent': 'leaveDestination', 'ambiguous': 'refuseItem'}
POLICY_VALUES = {'existing': ('replace', 'keepDestination', 'refuseConflict'), 'absent': ('leaveDestination', 'clearDestination'), 'ambiguous': ('refuseItem', 'skipField')}
E2_FIELDS = ('title', 'description', 'keywords', 'creator', 'copyright', 'rightsUrl', 'rating', 'locationCity', 'locationCountry')
EXTRA_VIEW = ('cameraMake', 'cameraModel', 'lensMakeE4', 'lensModelE4', 'bodySerialNumberE4', 'lensSerialNumberE4', 'exposureTimeE4', 'fNumberE4', 'focalLengthE4', 'exposureBiasE4',
              'isoSpeedE4', 'focalLength35mmE4')
E3_GROUPS = ('captureTime', 'location')      # carried by the E3 planners, writers and proofs; composed with the E2 edit plan and the extras into one write
KINDS = ('transfer',)
LOSSES = [
    'Selected typed values only: the copy receives the values of the fields the author chose, re-encoded by ExifTool from planner-chosen assignments. MakerNotes, unknown tags, thumbnails, whole blocks, XMP structures and every field that was not selected are neither copied nor read as transferred (no native -tagsFromFile). Orientation, image size, software and the modified and digitised times are never transferred.',
    'A field is transferred only when every source that records it agrees; an ambiguous source value is refused or skipped as declared, and an unreadable or unsupported source value is never treated as absent. Existing destination values follow the declared policy; list fields transfer as whole values (there is no merge).',
    'Text is exact and never normalised: NFC and NFD stay distinct and rational values keep their exact numerator and denominator (10/30 and 1/3 are different values). ',
    'Proof T compares the raw decoded literal of the source capture with the output and, key by key, the fixed ExifTool listings of both. Native agreement is reproducibility of the same engine, not independent truth.',
    'No Exif block or ExifIFD is created: a destination without one is refused, because the native writer would add mandatory values that can change what an untouched GPS-only height means. After every write the typed height is read again.',
    'The capture time and location groups are carried by the E3 time and location planners and writers, composed with the other groups into one native write and one proof set that includes the independent source-to-output proof T (a refusal of any selected part refuses the whole item, and no selected value is dropped from a successful item). A captured time is set as the source\'s exact local time, offset and fraction, also into a destination that records none (one carrier: an existing ExifIFD, otherwise XMP); a destination offset the source does not record, a different digit precision and an ExifIFD that would have to be created are refused; coordinates are rounded half-even to 9 decimal places with the difference recorded, an altitude only with its typed reference and exactly representable, and an altitude the edition cannot express is refused as E3 does.']


class Unavailable(ValueError):
    pass


# ---------------------------------------------------------------- the pinned extras write table
_CACHE = []


def digest():
    found = hashlib.sha256(files(__package__).joinpath(FILE).read_bytes()).hexdigest()
    if found != PIN:
        raise Unavailable('CATALOGUE_DIGEST_DRIFT: %s no longer has its pinned bytes (%s)' % (FILE, found))
    return found


def table():
    """The extras destinations (data, not per-field code), validated against the E4 catalogue view and against every other write table."""
    if not _CACHE:
        digest()
        data = json.loads(files(__package__).joinpath(FILE).read_text(encoding='utf-8'))
        known = catalogue.fields(VIEW)
        if data.get('version') != VERSION or data.get('catalogue') != VIEW or set(data) != {'version', 'catalogue', 'fields'}:
            raise Unavailable('extras table shape or version')
        reserved = {d['write'] for f in writes.fields().values() for d in f['destinations']}
        seen = set()
        for name, spec in data['fields'].items():
            if name not in known or name not in EXTRA_VIEW or not spec['destinations'] or spec['destinations'][0]['role'] != 'primary':
                raise Unavailable('extras field ' + name)
            for d in spec['destinations']:
                if d['write'] in reserved or d['write'] in seen:
                    raise Unavailable('extras destination collides: ' + d['write'])
                seen.add(d['write'])
                if d['family'] == 'exif':
                    match = [s for s in known[name]['sources'] if s['family'] == 'exif' and (s['ifd'], s['tag']) == (d['ifd'], d['tag'])]
                else:
                    match = [s for s in known[name]['sources'] if s['family'] == 'xmp' and s['property'] == d['property']]
                if len(match) != 1:
                    raise Unavailable('extras destination %s has no independent reader in the catalogue' % d['write'])
        _CACHE.append(data)
    return _CACHE[0]['fields']


# ---------------------------------------------------------------- static planning (document only)
def static_plan(op, p, media):
    try:
        selected = e4model.selection(p['transfer'])
    except e4model.SelectionError as error:
        raise edits.PlanError('INVALID_TRANSFER_SELECTION', error.message, error.location, **error.observed)
    given = p.get('policies', {})
    policies = {k: given.get(k, POLICY_DEFAULTS[k]) for k in POLICY_DEFAULTS}
    policies['loss'] = edits.normalise_policies(given.get('loss'))
    ids = [i['id'] for i in media['items']] if media['kind'] == 'items' else None
    source = p['source']
    if op == 'applySidecar':
        mode = source['sidecar']
        if (mode == 'declared') != (media['kind'] == 'items'):
            raise edits.PlanError('INVALID_SIDECAR_SOURCE', 'declared sidecars come with media.items entries that name a sidecar; adjacent sidecars come with a media.folder', '$.source.sidecar', mode=mode, media=media['kind'])
        if mode == 'declared' and not any('sidecar' in i for i in media['items']):
            raise edits.PlanError('INVALID_SIDECAR_SOURCE', 'declared needs at least one item with a sidecar path', '$.source.sidecar')
        block = {'kind': 'sidecar', 'mode': mode}
    elif 'item' in source:
        if ids is not None and source['item'] not in ids:
            raise edits.PlanError('UNKNOWN_ITEM', 'the source names an item that is not in media.items', '$.source.item', value=source['item'][:64], items=ids[:20])
        block = {'kind': 'item', 'item': source['item']}
    elif 'file' in source:
        path = source['file']['path']
        if '\0' in path or not path.startswith('/') or Path(path).suffix.lower() not in mediaset.IMAGE_SUFFIXES + ('.xmp',):
            raise edits.PlanError('INVALID_PHOTO_SOURCE', 'select an absolute .jpg, .jpeg or .xmp source file', '$.source.file.path')
        block = {'kind': 'file', 'path': path, **({'sha256': source['file']['sha256']} if 'sha256' in source['file'] else {})}
    else:
        pairs, seen = [], set()
        for index, entry in enumerate(source['pairs']):
            at = '$.source.pairs[%d]' % index
            for key in ('from', 'to'):
                if ids is not None and entry[key] not in ids:
                    raise edits.PlanError('UNKNOWN_ITEM', 'the pair names an item that is not in media.items', at + '.' + key, value=entry[key][:64], items=ids[:20])
            if entry['to'] in seen:
                raise edits.PlanError('INVALID_ARGUMENT', 'an item is the destination of more than one pair', at + '.to', value=entry['to'])
            seen.add(entry['to'])
            pairs.append({'from': entry['from'], 'to': entry['to']})
        block = {'kind': 'pairs', 'pairs': pairs}
    return {'source': block, 'transfer': {'groups': [g for g in e4model.GROUPS if g in p['transfer'].get('groups', [])], 'fields': selected}, 'policies': policies}


def reusable_inputs(p):
    found = {}
    source = p['source']
    if source['kind'] == 'file':
        found[source['path']] = hashlib.sha256(mediaset.read_file(source['path'], None, mediaset.ITEM_BYTES, '$.source.file.path')).hexdigest()
    return found


# ---------------------------------------------------------------- captured inputs and context
def capture(p, directory, media):
    """Capture the external source file into ``inputs/`` (run time only); returns the ``inputs`` record of ``captures.json`` (``{}`` for none)."""
    source = p['source']
    if source['kind'] != 'file':
        return {}
    (directory / INPUTS).mkdir(exist_ok=True)
    data = mediaset.read_file(source['path'], None, mediaset.ITEM_BYTES, '$.source.file.path')
    sha = hashlib.sha256(data).hexdigest()
    if source.get('sha256') and source['sha256'] != sha:
        from schemaxis.errors import fail
        fail('PHOTO_HASH_MISMATCH', 'the source file differs from the pinned sha256', '$.source.file.sha256', observed=sha)
    suffix = '.xmp' if Path(source['path']).suffix.lower() == '.xmp' else '.jpg'
    name = '%s/source%s' % (INPUTS, suffix)
    (directory / name).write_bytes(data)
    return {'source': {'source': source['path'], 'file': name, 'sha256': sha, 'bytes': len(data)}}


class Context:
    """The source file of a transfer, rebuilt identically at run time and in verification from the retained run directory."""

    def __init__(self, p, directory, captured):
        self.p, self.op, self.directory = p, p['operation'], directory
        self.block = p['source']
        self.policies = p['policies']
        self.selected = p['transfer']['fields']
        self.external = None
        inputs = captured.get('inputs', {})
        if 'source' in inputs:
            record = inputs['source']
            data = (directory / record['file']).read_bytes()
            if hashlib.sha256(data).hexdigest() != record['sha256'] or len(data) != record['bytes']:
                from schemaxis.errors import fail
                fail('CAPTURE_CHANGED', 'a retained captured input differs from its capture record', record['file'])
            self.external = {'record': record, 'data': data}


def input_names(captured):
    return {captured['inputs']['source']['file']} if 'source' in captured.get('inputs', {}) else set()


def extra_native_names(p, ctx, items):
    """Captured files beyond the destination JPEGs that the fixed ``before`` listing must also cover (sources and sidecars)."""
    names = []
    if ctx.external is not None:
        names.append(ctx.external['record']['file'])
    if p['operation'] == 'applySidecar':
        names += [i['sidecar']['file'] for i in items if i['status'] == 'ok' and i['sidecar']]
    return names


# ---------------------------------------------------------------- one item
def equal(field, a, b):
    shape = e4model.SHAPES[field]
    if shape == 'langText':
        return a['text'] == b['text'] and sorted((e['language'], e['text']) for e in a['languages']) == sorted((e['language'], e['text']) for e in b['languages'])
    if shape == 'bag':
        return sorted(a) == sorted(b)
    return a == b


def shown(value):
    if isinstance(value, tuple):
        return '%d/%d' % value
    return value


def anchor_fields(payloads, selected, index, version=VIEW):
    """The E4 view fields of the selection decoded from ``payloads`` and anchored against a native listing index; ``(fields, mismatches)``."""
    names = e4model.view_names(list(selected))
    rec = records.Record(payloads, version)
    fields = {n: rec.field(n) for n in names}
    checked, mismatches = listing.anchors({}, fields, {'image': index, 'sidecar': None})
    return fields, mismatches


def literal_text(value, limits, at, field, item=False):
    """The E2 text rules with one difference: leading and trailing U+0020 are kept. A transfer carries the source literal exactly (native 13.55 preserves such a title in XMP and IPTC);
    a blank-only text, any other edge white space, a control character and the length bound are refused as in ``edits.check_text``. The public editMetadata contract is unchanged."""
    if not isinstance(value, str):
        raise edits.PlanError('INVALID_ARGUMENT', 'expected text', at, field=field)
    core = value.strip(' ')
    if core == '' or core.strip() == '':
        raise edits.PlanError('EDIT_EMPTY_VALUE', 'an empty or white-space-only value reads back as absent', at, field=field)
    if core != core.strip():
        raise edits.PlanError('EDIT_VALUE_INVALID', 'edge white space other than U+0020 is not carried', at, field=field)
    edits.check_text(core, {**limits, 'maxChars': None, 'itemMaxChars': None}, at, field, item)
    maximum = limits.get('itemMaxChars' if item else 'maxChars')
    if maximum is not None and len(value) > maximum:
        raise edits.PlanError('EDIT_VALUE_TOO_LONG', 'the value exceeds %d characters' % maximum, at, field=field, characters=len(value))
    return value


def literal_lang(value, limits, at, field):
    """The language-alternative literal: the language keys are validated by the E2 rules (tag syntax, x-default, duplicates, count) on a stand-in whose texts are replaced by a placeholder, so
    that only the keys are judged there; every text, x-default and alternatives alike, is then judged and carried from the original source literal by ``literal_text``. The placeholder is never
    written and never substitutes a blank: a blank or control text is refused exactly."""
    out = edits.normalise_lang({'text': 'x', 'languages': [{'language': e['language'], 'text': 'x'} for e in value['languages']]}, limits, at, field)
    return {'text': literal_text(value['text'], limits, at + '.text', field),
            'languages': [{'language': e['language'], 'text': literal_text(value['languages'][i]['text'], limits, '%s.languages[%d].text' % (at, i), field)} for i, e in enumerate(out['languages'])]}


def text_problem(field, value, at):
    """The value domain of a transferred value: the E2 rules (language tags, duplicates, lists, integers, URLs), with the source text literal kept exactly; ``(value, None)`` or ``(None, problem)``."""
    try:
        spec = writes.fields()[field]
        shape = e4model.SHAPES[field]
        if shape == 'langText':
            return literal_lang(value, spec['limits'], at, field), None
        if shape in ('bag', 'seq'):
            edits.normalise_list([v.strip(' ') or 'x' for v in value], spec['limits'], at, field)
            return [literal_text(v, spec['limits'], '%s[%d]' % (at, i), field, item=True) for i, v in enumerate(value)], None
        if shape == 'integer':
            limits = spec['limits']
            if isinstance(value, bool) or not isinstance(value, int) or not limits['minimum'] <= value <= limits['maximum']:
                raise edits.PlanError('EDIT_VALUE_INVALID', 'use an integer from %d to %d' % (limits['minimum'], limits['maximum']), at, field=field)
            return value, None
        text = literal_text(value, spec['limits'], at, field)
        if spec['shape'] == 'url' and not edits.URL.fullmatch(text):
            raise edits.PlanError('EDIT_VALUE_INVALID', 'use an absolute http or https URL without white space', at, field=field)
        return text, None
    except edits.PlanError as error:
        return None, {'code': error.code, 'message': error.message, **{k: v for k, v in error.observed.items() if k in ('codePoint', 'position', 'characters')}}


def extra_value_problem(view_field, spec, value, policies, at):
    shape = spec['shape']
    limits = spec['limits']
    if shape == 'text':
        if not isinstance(value, str) or value == '' or value != value.strip() or any(ord(c) < 32 or 0x7F <= ord(c) <= 0x9F for c in value):
            return {'code': 'TRANSFER_VALUE_NOT_REPRESENTABLE', 'message': 'an empty, edge-white-space or control-character text does not read back identically', 'field': view_field}
        if len(value.encode('utf-8')) > limits['maxChars']:
            return {'code': 'TRANSFER_VALUE_NOT_REPRESENTABLE', 'message': 'the EXIF text form holds at most %d bytes' % limits['maxChars'], 'field': view_field, 'bytes': len(value.encode('utf-8'))}
        if policies['loss']['exifEncoding'] == 'ascii' and not edits.ascii_text(value):
            return {'code': 'TRANSFER_VALUE_NOT_REPRESENTABLE', 'message': 'the exifEncoding policy is ascii and the value is not ASCII', 'field': view_field}
    elif shape in ('rational', 'srational'):
        n, d = value
        if d == 0 or (shape == 'rational' and n < 0) or abs(n) >= 2 ** 32 or d >= 2 ** 32:
            return {'code': 'TRANSFER_VALUE_NOT_REPRESENTABLE', 'message': 'the pair does not fit an EXIF %s (32-bit parts, positive denominator, no sign in an unsigned form)' % ('SRATIONAL' if shape == 'srational' else 'RATIONAL'), 'field': view_field, 'pair': '%d/%d' % (n, d)}
    else:
        if not limits['minimum'] <= value <= limits['maximum']:
            return {'code': 'TRANSFER_VALUE_NOT_REPRESENTABLE', 'message': 'the value is outside the EXIF SHORT range %d to %d' % (limits['minimum'], limits['maximum']), 'field': view_field, 'value': value}
    return None


def extra_argument(d, shape, value):
    if shape in ('rational', 'srational'):
        return '-%s=%d/%d' % (d['write'], value[0], value[1])
    return '-%s=%s' % (d['write'], value)


def extras_plan(requests, payloads, policies, at):
    """The destination decisions of the extras: ``[{'field', 'viewField', 'action', 'value', 'destinations': [...]}]`` or a Refusal."""
    out = []
    spec_table = table()
    exif_state = payloads.exif
    for view_field, req in requests.items():
        spec = spec_table[view_field]
        if req['action'] == 'set' and exif_state[0] != 'ok':
            raise edits.Refusal('TRANSFER_WOULD_CREATE_EXIF', 'the destination has no readable Exif block, and creating one would add mandatory values this transfer does not request', at, field=view_field,
                                cause=exif_state[2] if exif_state[0] == 'error' else exif_state[1] if len(exif_state) > 1 else exif_state[0])
        if req['action'] == 'set':
            problem = extra_value_problem(view_field, spec, req['value'], policies, at)
            if problem:
                raise edits.Refusal(problem['code'], problem['message'], at, **{k: v for k, v in problem.items() if k not in ('code', 'message')})
        destinations = []
        for d in spec['destinations']:
            entry = {'family': d['family'], 'write': d['write'], 'listing': d['listing']}
            if d['family'] == 'exif':
                read = edits.read_exif(payloads, {**d, 'editorPart': False}) if exif_state[0] == 'ok' else {'state': 'absent'}
                if exif_state[0] == 'ok' and d['ifd'] == 'ExifIFD' and req['action'] == 'set' and payloads.exif[1]['ifds'].get('ExifIFD') is None:
                    raise edits.Refusal('TRANSFER_WOULD_CREATE_EXIF', 'the destination has no ExifIFD, and creating it would add mandatory values (such as ExifVersion) that can change what an untouched GPS-only height means', at, field=view_field)
                if read['state'] == 'unreadable' or (read['state'] == 'present' and read.get('undecodable') and spec['shape'] == 'text'):
                    raise edits.Refusal('TRANSFER_DESTINATION_UNREADABLE', 'the current EXIF value of this field cannot be read back, so it is not overwritten', at, field=view_field, cause=read.get('code') or read.get('undecodable'))
                entry['state'] = 'write' if req['action'] == 'set' else ('delete' if (read['state'] != 'absent' or exif_has(payloads, d)) else 'skip')
                entry.update(ifd=d['ifd'], tag=d['tag'])
            else:
                read = edits.read_xmp(payloads, d)
                if read['state'] == 'unreadable':
                    raise edits.Refusal('TRANSFER_DESTINATION_UNREADABLE', 'the current XMP value of this field cannot be read back, so it is not overwritten', at, field=view_field, cause=read.get('code'))
                if read['state'] != 'present':
                    entry['state'] = 'skip'
                    entry['reason'] = 'noXmpProperty'
                else:
                    entry['state'] = 'write' if req['action'] == 'set' else 'delete'
                entry['property'] = d['property']
            entry['before'] = read
            if entry['state'] == 'write':
                entry['argument'] = extra_argument(d, spec['shape'], req['value'])
            elif entry['state'] == 'delete':
                entry['argument'] = '-%s=' % d['write']
            destinations.append(entry)
        out.append({'field': req['field'], 'viewField': view_field, 'shape': spec['shape'], 'action': req['action'], 'value': req.get('value'), 'destinations': destinations})
    return out


def exif_has(payloads, d):
    """Whether the tag exists in the destination IFD although its value is unreadable (a clear then deletes it)."""
    state = payloads.exif
    group = state[1]['ifds'].get(d['ifd']) if state[0] == 'ok' else None
    return bool(group and group[0] == 'ok' and any(e.tag == int(d['tag'], 16) for e in group[1]))


def source_of(p, ctx, item, by_id, before, directory, admitted):
    """``(payloads, native index, label)`` of the source snapshot of one destination, or a Refusal."""
    block = ctx.block
    at = '$.source'
    if block['kind'] in ('item', 'pairs'):
        if block['kind'] == 'item':
            source_id = block['item']
        else:
            pair = next((x for x in block['pairs'] if x['to'] == item['id']), None)
            if pair is None:
                raise edits.Refusal('TRANSFER_NOT_A_DESTINATION', 'the item is not the destination of any pair, so nothing is transferred to it', at + '.pairs', item=item['id'])
            source_id = pair['from']
        source = by_id.get(source_id)
        if source is None:
            raise edits.Refusal('UNKNOWN_ITEM', 'the source item is not in the media set', at, value=source_id[:64], items=sorted(by_id)[:20])
        if source_id == item['id']:
            raise edits.Refusal('TRANSFER_SELF', 'a destination equal to its own source has nothing to transfer', at, item=item['id'])
        if source_id not in admitted:
            raise edits.Refusal('TRANSFER_SOURCE_MISSING', 'the source item was not admitted, so no snapshot of it exists', at, source=source_id, cause=source['fault'])
        return source['payloads'], listing.index(source['beforeRecord']), 'item:' + source_id, source['sha256']
    if block['kind'] == 'file':
        ext = ctx.external
        key = ext['record']['file']
        record = before[key]
        located = containers.locate(ext['data'])
        return records.Payloads(located), listing.index(record), 'file', ext['record']['sha256'], record
    if not item['sidecar']:
        raise edits.Refusal('SIDECAR_ABSENT', 'the item has no sidecar to apply', at, item=item['id'])
    key = item['sidecar']['file']
    side_data = legacy.bounded(directory / key, limit=mediaset.ITEM_BYTES)
    located = containers.locate(side_data)
    return records.Payloads(located), listing.index(before[key]), 'sidecar', item['sidecar']['sha256'], before[key]


def decide(field, src, dst, policies):
    """The decision of one field: ``(action, reason)`` with action write, clear, unchanged, keep, skip, or a ``Refusal``."""
    at = '$.transfer.' + field
    s, d = src['state'], dst['state']
    if s in ('unreadable', 'unsupported'):
        if policies['ambiguous'] == 'skipField':
            return 'skip', 'sourceUnreadable'
        raise edits.Refusal('TRANSFER_SOURCE_UNREADABLE', 'the source value of this field cannot be read, so it is never treated as absent', at, field=field, state=s, sources=src.get('sources'))
    if s == 'ambiguous':
        if policies['ambiguous'] == 'skipField':
            return 'skip', 'sourceAmbiguous'
        raise edits.Refusal('TRANSFER_SOURCE_AMBIGUOUS', 'the sources of this field disagree, so no single value is chosen', at, field=field, sources=src.get('sources'))
    if s == 'absent':
        if policies['absent'] == 'leaveDestination' or d == 'absent':
            return 'unchanged', 'sourceAbsent'
        if d in ('unreadable', 'unsupported'):
            raise edits.Refusal('TRANSFER_DESTINATION_UNREADABLE', 'the destination value cannot be read, so it is not cleared', at, field=field, state=d)
        return 'clear', 'sourceAbsentCleared'
    if d == 'absent':
        return 'write', 'destinationAbsent'
    if d == 'present' and equal(field, src['value'], dst['value']):
        return 'unchanged', 'equal'
    if d in ('unreadable', 'unsupported'):
        raise edits.Refusal('TRANSFER_DESTINATION_UNREADABLE', 'the destination value cannot be read, so it is not overwritten', at, field=field, state=d)
    if policies['existing'] == 'replace':
        return 'write', 'replaced'
    if policies['existing'] == 'keepDestination':
        return 'keep', 'keepDestination'
    raise edits.Refusal('TRANSFER_CONFLICT', 'the destination already has a different value and the policy refuses a conflict', at, field=field, source=shown(src['value']) if not isinstance(src['value'], dict) else src['value'],
                        destination=shown(dst.get('value')) if not isinstance(dst.get('value'), dict) else dst.get('value'), destinationState=d,
                        **({'rationalPairDiffers': True} if isinstance(src['value'], tuple) and isinstance(dst.get('value'), tuple) and src['value'][0] * dst['value'][1] == dst['value'][0] * src['value'][1] else {}))


def decimal9(value):
    """A coordinate (exact Fraction degrees) as the E3 request text: half-even to 9 decimal places; returns ``(text, differenceDegrees)``."""
    from decimal import Decimal, ROUND_HALF_EVEN
    exact = Decimal(value.numerator) / Decimal(value.denominator)
    rounded = exact.quantize(Decimal('1.000000000'), rounding=ROUND_HALF_EVEN)
    return format(rounded, 'f'), float(abs(exact - rounded))


def location_request(src, losses):
    """The E3 position request of a source location row (decimal text only), with every omission recorded as a loss."""
    from decimal import Decimal
    from schemaxis.adaptors.exiftool import locations
    from fractions import Fraction
    lat, lat_diff = decimal9(src['exactDegrees']['latitude'])
    lon, lon_diff = decimal9(src['exactDegrees']['longitude'])
    request = {'latitude': lat, 'longitude': lon}
    quantisation = {'latitude': {'written': lat, 'differenceDegrees': lat_diff}, 'longitude': {'written': lon, 'differenceDegrees': lon_diff}}
    height = src['height']
    if height['state'] == 'present':
        if height['reference'] in ('ellipsoidal', 'seaLevel') and height['signKnown']:
            n, d = height['stored']
            magnitude = Fraction(n, d)
            if (magnitude * 1000).denominator == 1 and magnitude < 100000:
                text = format((Decimal(n) / Decimal(d)).quantize(Decimal('1.000')), 'f')
                request['altitude'] = {'meters': ('-' if height['meters'].startswith('-') else '') + text, 'reference': height['reference']}
            else:
                losses.append({'code': 'altitudeNotRepresentable', 'field': 'location.height', 'treatment': 'altitudeOmitted'})
        else:
            losses.append({'code': 'altitudeReferenceUnspecified', 'field': 'location.height', 'treatment': 'altitudeOmitted'})
    elif height['state'] != 'absent':
        losses.append({'code': 'altitudeUnreadable', 'field': 'location.height', 'state': height['state'], 'treatment': 'altitudeOmitted'})
    if src['datum']['state'] == 'present':
        try:
            locations.parse_datum(src['datum']['value'], 'datum')
            request['datum'] = src['datum']['value']
        except locations.LocationProblem:
            losses.append({'code': 'datumNotTransferable', 'field': 'location.datum', 'treatment': 'datumOmitted'})
    if src['gpsUtc']['state'] != 'absent':
        losses.append({'code': 'gpsDateTimeNotTransferred', 'field': 'location', 'treatment': 'omitted'})
    return request, quantisation


def location_part(p, ctx, item, src_snap, dst_snap, label, source_sha):
    """The location part of one item's transfer (decisions here, the plan, write and proofs of the E3 location family); ``(plan, decisions)``, plan ``None`` when nothing is written."""
    from schemaxis.adaptors.exiftool import e3place, e3write
    from schemaxis.core.faults import SchemaxisError
    at = '$.transfer.location'
    src, dst = src_snap['location'], dst_snap['location']
    decisions = [{'field': 'location', 'sourceState': src['state'], 'destinationState': dst['state']}]
    if src['state'] == 'present':
        request, quantisation = location_request(src, [])
        same = dst['state'] == 'present' and (decimal9(dst['exactDegrees']['latitude'])[0], decimal9(dst['exactDegrees']['longitude'])[0]) == (request['latitude'], request['longitude'])
        src_view = {'latitude': request['latitude'], 'longitude': request['longitude']}
    else:
        same, src_view = False, None
    dst_view = dst['position'].get('latitude') and {'latitude': dst['position']['latitude'], 'longitude': dst['position']['longitude']}
    try:
        e3_gate(ctx, 'location', src, dst, same, src_view, dst_view, decisions)
    except edits.Refusal as stop:
        if stop.code == 'ITEM_UNCHANGED':
            return None, decisions
        raise
    losses = []
    request, quantisation = location_request(src, losses)
    try:
        parsed = e3place.parse_entry(request, None, at)
    except SchemaxisError as error:
        raise edits.Refusal('TRANSFER_VALUE_NOT_REPRESENTABLE', error.fault.message, at, field='location', cause=error.fault.code)
    plan_ = e3place.plan_item(parsed, item['payloads'], item['walk'], e3write.policies_of('setLocation', {'createExif': 'refuse'}), item['file'])
    problem = e3place.xmp_qualifier_problem(item['located'], plan_['xmpTargets'])
    if problem:
        raise edits.Refusal('XMP_QUALIFIERS_WOULD_BE_LOST', 'an XMP value this write rewrites carries qualifiers that the rewrite would silently drop, so the item is refused rather than flattened', item['file'], **problem)
    plan_.update(outcome='located', iptc={'assignCharset': False, 'changed': False, 'digest': False, 'state': None, 'charset': None, 'created': False}, quantisation=quantisation)
    plan_['losses'] = list(plan_.get('losses', [])) + losses
    return plan_, decisions


def nothing_to_clear(field, dst):
    """Whether the destination records nothing of an E3-carried group, so that an absent source with ``clearDestination`` is genuinely unchanged (an unreadable or partial value is something to clear)."""
    if dst['state'] != 'absent':
        return False
    if field == 'captureTime':
        return not any(row['state'] != 'absent' for rows in dst['sources'].values() for row in rows)
    return dst['height']['state'] == 'absent' and dst['datum']['state'] == 'absent' and dst['gpsUtc']['state'] == 'absent'


def e3_gate(ctx, field, src, dst, same, source_view, destination_view, decisions):
    """The policy decisions shared by the E3-carried groups: returns on ``write`` and raises the precise Refusal (or ITEM_UNCHANGED) otherwise."""
    policies, at = ctx.policies, '$.transfer.' + field

    def stop(reason, code=None, message=None, **observed):
        decisions[0].update(action='unchanged' if code is None else 'refuse', reason=reason)
        if code is None:
            raise edits.Refusal('ITEM_UNCHANGED', 'nothing is written for this item: ' + reason, '$', reason=reason, decisions=decisions)
        raise edits.Refusal(code, message, at, field=field, **observed)
    if src.get('code') == e4model.UNANCHORED_CODE:
        if policies['ambiguous'] == 'skipField':
            stop('sourceUnanchored')
        message, observed = e4model.unanchored_problem(src['unanchored'], 'source')
        stop('sourceUnanchored', 'TRANSFER_TIME_COMPONENT_UNANCHORED', message, **{k: v for k, v in observed.items() if k != 'field'})
    if src['state'] in ('unreadable', 'unsupported'):
        if policies['ambiguous'] == 'skipField':
            stop('sourceUnreadable')
        stop('sourceUnreadable', 'TRANSFER_SOURCE_UNREADABLE', 'the source %s cannot be read, so it is never treated as absent' % field, state=src['state'])
    if src['state'] == 'ambiguous':
        if policies['ambiguous'] == 'skipField':
            stop('sourceAmbiguous')
        stop('sourceAmbiguous', 'TRANSFER_SOURCE_AMBIGUOUS', 'the %s sources disagree, so no single value is chosen' % field)
    if src['state'] == 'absent':
        if policies['absent'] == 'clearDestination' and not nothing_to_clear(field, dst):
            stop('sourceAbsent', 'TRANSFER_E3_CLEAR_UNSUPPORTED', 'removing a destination %s is removeMetadata, not a transfer' % field)
        stop('sourceAbsent')
    if dst.get('code') == e4model.UNANCHORED_CODE:
        if policies['existing'] == 'keepDestination':
            stop('keepDestination')
        message, observed = e4model.unanchored_problem(dst['unanchored'], 'destination')
        stop('destinationUnanchored', 'TRANSFER_TIME_COMPONENT_UNANCHORED', message, **{k: v for k, v in observed.items() if k != 'field'})
    if dst['state'] in ('unreadable', 'unsupported'):
        stop('destinationUnreadable', 'TRANSFER_DESTINATION_UNREADABLE', 'the destination %s cannot be read, so it is not overwritten' % field, state=dst['state'])
    if dst['state'] in ('present', 'ambiguous'):
        if dst['state'] == 'present' and same:
            stop('equal')
        if policies['existing'] == 'keepDestination':
            stop('keepDestination')
        if policies['existing'] == 'refuseConflict':
            stop('conflict', 'TRANSFER_CONFLICT', 'the destination already records a different %s and the policy refuses a conflict' % field, source=source_view, destination=destination_view, destinationState=dst['state'])
    decisions[0].update(action='write', reason='destinationAbsent' if dst['state'] == 'absent' else 'replaced')


def time_part(p, ctx, item, src_snap, dst_snap, label, source_sha):
    """The captured-time part of one item's transfer (decisions here; the plan, write and proofs are the E3 time family's, through its shared ``time_plan`` with an absolute move); ``(plan, decisions)``, plan ``None`` when nothing is written."""
    from schemaxis.adaptors.exiftool import e3read, e3write, timecalc as tc
    src, dst = src_snap['captureTime'], dst_snap['captureTime']
    decisions = [{'field': 'captureTime', 'sourceState': src['state'], 'destinationState': dst['state']}]
    s = src.get('value') or {}
    d = dst.get('value') or {}
    try:
        e3_gate(ctx, 'captureTime', src, dst, dst['state'] == 'present' and s == d, s, d, decisions)
    except edits.Refusal as stop:
        if stop.code == 'ITEM_UNCHANGED':
            return None, decisions
        if stop.code == 'TRANSFER_TIME_COMPONENT_UNANCHORED' and stop.observed.get('side') == 'destination':
            raise edits.Refusal(stop.code, stop.message, item['file'], **stop.observed)
        raise
    at = item['file']
    if d.get('offset') is not None and s.get('offset') is None:
        raise edits.Refusal('TRANSFER_TIME_OFFSET_CONFLICT', 'the destination records a UTC offset that the source does not, and an offset can be set but not removed here, so the contrary destination value is not silently kept', at, field='captureTime', destination=d['offset'])
    reader = records.Record(item['payloads'], e3write.VIEW)
    item['e3fields'] = {name: reader.field(name) for name in e3read.field_names('reconcileTime')}
    try:
        tc.parse_local(s['local'])
    except tc.TimeProblem as error:
        raise edits.Refusal('TRANSFER_VALUE_NOT_REPRESENTABLE', error.message, at, field='captureTime', cause=error.code)
    # the internal absolute set intent: the exact source local time, fraction digits and offset, never a move computed from the destination
    intent = {'local': s['local'], 'fraction': s.get('sub') or '', 'offset': s.get('offset')}
    block = {'timeFields': ['captured'], 'policies': e3write.policies_of('correctTime', {})}
    try:
        plan_ = e3write.time_plan(block, item, 'transfer', {'group': 'captured'}, 0, None, 'absolute', None, at, absolute=intent)
    except edits.Refusal as stop:
        mapped = {'TIME_OFFSET_REMOVAL': 'TRANSFER_TIME_OFFSET_CONFLICT', 'TIME_FRACTION_PRECISION': 'TRANSFER_TIME_FRACTION_PRECISION'}.get(stop.code)
        if mapped is None:
            raise
        raise edits.Refusal(mapped, stop.message, stop.location, **stop.observed)
    # a destination IPTC time (2:60) without its date (2:55) is no carrier the write replaces or anchors: it would stay and be merged with the written local time, so a write is refused
    iptc_orphans = [c for c in dst.get('unanchored', []) if c['family'] == 'iptc']
    if plan_['kind'] != 'unchanged' and iptc_orphans:
        message, observed = e4model.unanchored_problem(iptc_orphans, 'destination')
        raise edits.Refusal('TRANSFER_TIME_COMPONENT_UNANCHORED', message, at, **observed)
    if plan_['kind'] == 'unchanged':
        if d == s and dst['state'] == 'present':
            decisions[0].update(action='unchanged', reason='equal')
            return None, decisions
        raise edits.Refusal('TRANSFER_TIME_NOT_APPLIED', 'the captured time the source records is not what the destination records, and no carrier of the destination would change: it is refused rather than reported unchanged', at,
                            field='captureTime', source=s, destination=d or None, planner=plan_.get('reason'))
    return plan_, decisions


def plan_item(p, ctx, item, by_id, before, directory, admitted):
    selected = ctx.selected
    policies = ctx.policies
    source = source_of(p, ctx, item, by_id, before, directory, admitted)
    payloads_src, index_src, label, source_sha = source[:4]
    fields_src, mismatches = anchor_fields(payloads_src, selected, index_src)
    if mismatches:
        raise edits.Refusal('NATIVE_ANCHOR_MISMATCH', 'ExifTool and the independent reader disagree about the source, so it is not transferred', '$.source', count=len(mismatches), mismatches=mismatches[:listing.ANCHOR_REPORT])
    src_snap = e4model.snapshot(payloads_src, selected)
    dst_snap = e4model.snapshot(item['payloads'], selected)
    decisions, item_edits, requests, e3_parts = [], {}, {}, {}
    for field in selected:
        if field in E3_GROUPS:
            plan_part, part_decisions = (location_part if field == 'location' else time_part)(p, ctx, item, src_snap, dst_snap, label, source_sha)
            decisions += part_decisions
            if plan_part is not None:
                e3_parts['location' if field == 'location' else 'time'] = plan_part
            continue
        src, dst = src_snap[field], dst_snap[field]
        action, reason = decide(field, src, dst, policies)
        entry = {'field': field, 'action': action, 'reason': reason, 'sourceState': src['state'], 'destinationState': dst['state']}
        if src['state'] == 'present':
            entry['value'] = jsonable_value(src['value'])
        decisions.append(entry)
        if action in ('write', 'clear'):
            view_field = e4model.VIEW_FIELD.get(field, field)
            if field in E2_FIELDS:
                if action == 'write':
                    value, problem = text_problem(field, src['value'], '$.transfer.' + field)
                    if problem:
                        raise edits.Refusal('TRANSFER_VALUE_NOT_REPRESENTABLE', problem['message'], '$.transfer.' + field, field=field, cause=problem['code'], **{k: v for k, v in problem.items() if k not in ('code', 'message')})
                    item_edits[field] = {'set': value}
                else:
                    item_edits[field] = {'clear': True}
            else:
                requests[view_field] = {'field': field, 'action': 'set' if action == 'write' else 'clear', **({'value': src['value']} if action == 'write' else {})}
    if not item_edits and not requests and not e3_parts:
        raise edits.Refusal('ITEM_UNCHANGED', 'nothing is written for this item: every selected field is equal, absent, kept or skipped', '$', reason=decisions[0]['reason'] if len(decisions) == 1 else 'nothingToTransfer', decisions=decisions[:24])
    e2 = None
    if item_edits:
        from schemaxis.adaptors.exiftool import editing
        e2 = edits.plan_item(item_edits, item['payloads'], policies['loss'], editing.digest_present(item))
        e2['kind'] = 'edit'
        if item['walk'] is None:       # a container: the shared TIFF/DNG IPTC digest rules apply before the native arguments are built
            e5edit.tiff_iptc_guard(item['container'], e2, editing.digest_present(item), item['located'])
    extras = extras_plan(requests, item['payloads'], policies, item['file']) if requests else []
    args = (edits.assignments(e2) if e2 else []) + [d['argument'] for x in extras for d in x['destinations'] if 'argument' in d]
    for part in e3_parts.values():
        args += [a for a in part['args'] if a != '-n' and a not in args]
    if e3_parts:
        args = ['-n'] + args
    if not args:
        raise edits.Refusal('ITEM_UNCHANGED', 'nothing is written for this item: every planned destination is skipped', '$', reason='nothingToWrite', decisions=decisions[:24])
    exif_extra = any(d['family'] == 'exif' and d['state'] in ('write', 'delete') for x in extras for d in x['destinations'])
    xmp_extra = any(d['family'] == 'xmp' and d['state'] in ('write', 'delete') for x in extras for d in x['destinations'])
    iptc = dict(e2['iptc']) if e2 else {'state': None, 'charset': None, 'assignCharset': False, 'changed': False, 'digest': False, 'created': False}
    declared = {'xmp': bool(e2 and e2['declared']['xmp']) or xmp_extra, 'iptc': bool(e2 and e2['declared']['iptc']), 'exif': bool(e2 and e2['declared']['exif']) or exif_extra}
    losses = list(e2 and [l for f in e2['fields'].values() for l in f['losses']] or [])
    xmp_written = bool(e2 and e2['xmpWritten']) or xmp_extra
    for part in e3_parts.values():
        losses += list(part.get('losses', []))
        for key in ('xmp', 'iptc', 'exif'):
            declared[key] = declared[key] or bool(part['declared'].get(key))
        iptc['changed'] = iptc['changed'] or bool(part['iptc']['changed'])
        iptc['digest'] = iptc['digest'] or bool(part['iptc']['digest'])
        xmp_written = xmp_written or bool(part['xmpWritten'])
        if part['iptc']['digest'] and '-Photoshop:IPTCDigest=new' not in args:
            args.append('-Photoshop:IPTCDigest=new')
    plan_ = {'kind': 'transfer', 'outcome': 'transferred', 'edit': e2, 'extras': extras, 'time': e3_parts.get('time'), 'location': e3_parts.get('location'), 'decisions': decisions, 'args': args, 'declared': declared,
             'iptc': iptc, 'xmpWritten': xmp_written, 'losses': losses, 'source': {'label': label, 'sha256': source_sha}}
    if 'location' in e3_parts:
        plan_['quantisation'] = e3_parts['location']['quantisation']
    e5edit.write_guards(item, plan_)
    return plan_, (payloads_src, index_src)


def jsonable_value(value):
    if isinstance(value, tuple):
        return '%d/%d' % value
    return value


def plan_items(p, items, before, ctx, directory):
    """Plan every ok destination item; a refusal turns the item into a refused outcome and the others continue."""
    from schemaxis.adaptors.exiftool import editing, e3write
    by_id = {i['id']: i for i in items}
    selected = ctx.selected
    admitted = {i['id'] for i in items if i['status'] == 'ok'}      # a source is read from its capture whatever happens to it as a destination
    for item in items:
        if item['status'] != 'ok':
            continue
        try:
            record = before[item['file']]
            problem = editing.native_input_problems(record)
            if problem:
                raise edits.Refusal(problem[0], problem[1])
            _, mismatches = anchor_fields(item['payloads'], selected, listing.index(record))
            if mismatches:
                raise edits.Refusal('NATIVE_ANCHOR_MISMATCH', 'ExifTool and the independent reader disagree about this capture, so it is not rewritten', item['file'], count=len(mismatches), mismatches=mismatches[:listing.ANCHOR_REPORT])
        except edits.Refusal as error:
            e3write.refused(item, error)
    for item in items:
        if item['status'] != 'ok':
            continue
        try:
            plan_, source = plan_item(p, ctx, item, by_id, before, directory, admitted)
            xmp_loss = editing.xmp_qualifier_loss({**item, 'plan': plan_['edit']}) if plan_.get('edit') else None
            if xmp_loss:
                raise edits.Refusal('XMP_QUALIFIERS_WOULD_BE_LOST', 'an XMP value this transfer rewrites carries qualifiers (item attributes or qualifier structures) that the rewrite would silently drop, so the item is refused rather than flattened',
                                    '$.transfer.' + xmp_loss['field'], property=xmp_loss['property'], qualifiers=xmp_loss['count'])
            item['plan'] = plan_
            item['transferSource'] = {'payloads': source[0], 'index': source[1]}
            item['beforeFields'] = {name: {'state': f['state'], 'reconciliation': f['reconciliation']} for name, f in records.build(item['located'], list(plan_['edit']['fields']), None, catalogue.VERSION_MWG)[1].items()} if plan_.get('edit') else {}
            item['args'] = plan_['args']
        except edits.Refusal as error:
            e3write.refused(item, error)
        except containers.Refused as error:
            e3write.refused(item, edits.Refusal(error.code, error.message, '$.source'))


# ---------------------------------------------------------------- proofs
def exif_scope(plan_):
    from schemaxis.adaptors.exiftool import editing
    targets = set()
    if plan_['edit']:
        targets |= editing.exif_scope(plan_['edit'])[0]
    for x in plan_['extras']:
        for d in x['destinations']:
            if d['family'] == 'exif' and d['state'] in ('write', 'delete'):
                targets.add((d['ifd'], int(d['tag'], 16)))
    for part in (plan_.get('time'), plan_.get('location')):
        if part:
            targets |= {tuple(t) for t in part.get('exifTargets', ())}
    return targets


def xmp_scope(plan_):
    """The XMP properties the whole plan names: the E2 destinations of its fields, the extras' XMP destinations and the targets of the time and location parts."""
    props = set()
    if plan_['edit']:
        for name in plan_['edit']['fields']:
            props |= {d['property'] for d in writes.fields()[name]['destinations'] if d['family'] == 'xmp'}
    for x in plan_['extras']:
        props |= {d['property'] for d in x['destinations'] if d['family'] == 'xmp' and d['state'] in ('write', 'delete')}
    for part in (plan_.get('time'), plan_.get('location')):
        if part:
            props |= set(part.get('xmpTargets', ()))
    return props


def iptc_scope(plan_):
    """The IPTC datasets the whole plan names (E2 companions and the time part's date, time and digest datasets), so that no part's untouched check ignores another part's targets."""
    touched = set()
    if plan_['edit']:
        for name in plan_['edit']['fields']:
            touched |= {(d['record'], d['dataset']) for d in writes.fields()[name]['destinations'] if d['family'] == 'iptc'}
    for part in (plan_.get('time'), plan_.get('location')):
        if part:
            touched |= {tuple(t) for t in part.get('iptcTargets', ())}
    return touched


def native_targets(plan_):
    from schemaxis.adaptors.exiftool import e3proofs as e3
    keys = set()
    for x in plan_['extras']:
        for d in x['destinations']:
            if d['state'] in ('write', 'delete'):
                keys.add(d['listing'])
    for part in (plan_.get('time'), plan_.get('location')):
        if part:
            keys |= e3.native_targets(part)
    return keys


def extras_readback(plan_, payloads_out, at):
    """R of the extras: every written value reads back exactly (text, exact pair, integer) and every cleared value reads back absent."""
    problems = []
    rec = records.Record(payloads_out, VIEW)
    for x in plan_['extras']:
        field = rec.field(x['viewField'])
        here = '%s.fields.%s' % (at, x['field'])
        if x['action'] == 'set':
            if field['state'] != 'present' or field['canonical'] != x['value'] and not (isinstance(x['value'], tuple) and tuple(field['canonical']) == x['value']):
                problems.append(proofs.problem('READBACK_MISMATCH', 'a transferred value does not read back exactly', here, expected=jsonable_value(x['value']), found=jsonable_value(field['canonical']) if field['state'] == 'present' else field['state']))
            elif field['reconciliation'] not in ('single-source', 'consistent'):
                problems.append(proofs.problem('READBACK_NOT_CONCORDANT', 'the sources of a transferred field do not agree after the write', here, reconciliation=field['reconciliation']))
        elif field['state'] != 'absent':
            problems.append(proofs.problem('READBACK_MISMATCH', 'a cleared value is still present', here, found=field['state']))
    return problems


def by_group1(index, key):
    """Native tokens of ``group1:name`` (the spelling of the write tables) in an index keyed ``group0:group1:name``, in key order."""
    found = []
    for k in sorted(index):
        if k.partition(':')[2] == key:
            found.extend(index[k])
    return found


# ---- proof T for the E3-carried groups: the source capture against the output, with expectations that do not come from the planner's request
HALF_UNIT = Fraction(1, 10 ** 9)           # the declared quantisation: coordinates are written as decimal degrees rounded half-even to 9 places
SERIALISATION = Fraction(2, 10 ** 10)      # the stored degree/minute/second rationals stay within 2e-10 degrees of the decimal (restated here: T does not import the bound it checks)


def height_expectation(height):
    """The typed height a destination must read after a transfer: ``None`` for an omitted altitude, else ``(reference, signed exact metres)``. Rules restated from the declared transfer
    (a known vertical reference and sign, at most millimetre precision, below 100 km), independently of the request the planner built."""
    if height['state'] != 'present' or height['reference'] not in ('ellipsoidal', 'seaLevel') or not height['signKnown']:
        return None
    n, d = height['stored']
    magnitude = Fraction(n, d)
    if (magnitude * 1000).denominator != 1 or magnitude >= 100000:
        return None
    return height['reference'], (-magnitude if height['meters'].startswith('-') else magnitude)


def location_problems(src, out, losses, here):
    """T-host of a location write: the source capture's typed values (exact coordinates, height with its reference and sign, datum) against the output's, within the declared quantisation."""
    if out['state'] != 'present':
        return [proofs.problem('TRANSFER_READBACK_MISMATCH', 'the transferred location does not read back as present', here, state=out['state'])]
    problems = []
    for axis in ('latitude', 'longitude'):
        want, got = src['exactDegrees'][axis], out['exactDegrees'][axis]
        rounded = Fraction(round(want * 10 ** 9), 10 ** 9)           # Python rounds a Fraction half-even
        if abs(got - rounded) > SERIALISATION or abs(got - want) > HALF_UNIT / 2 + SERIALISATION:
            problems.append(proofs.problem('TRANSFER_READBACK_MISMATCH', 'the output %s differs from the source beyond the declared 9-decimal half-even quantisation' % axis, here + '.' + axis,
                                           source=str(float(want)), output=str(float(got)), differenceDegrees=float(abs(got - want)), declaredBoundDegrees=float(HALF_UNIT / 2 + SERIALISATION)))
    expected = height_expectation(src['height'])
    found = out['height']
    if expected is None:
        if found['state'] != 'absent':
            problems.append(proofs.problem('TRANSFER_READBACK_MISMATCH', 'the source altitude is not transferred (declared loss) but the output records one', here + '.height', found=found['state']))
        if src['height']['state'] == 'present' and not any(l.get('field') == 'location.height' for l in losses):
            problems.append(proofs.problem('TRANSFER_LOSS_UNDECLARED', 'an omitted source altitude is not among the declared losses', here + '.height'))
    elif found['state'] != 'present' or found['reference'] != expected[0] or Fraction(found['meters']) != expected[1]:
        problems.append(proofs.problem('TRANSFER_READBACK_MISMATCH', 'the output altitude differs from the source (typed reference, sign and exact metres)', here + '.height',
                                       expected={'reference': expected[0], 'meters': str(float(expected[1]))}, found={k: found.get(k) for k in ('state', 'reference', 'meters')}))
    datum = src['datum']
    if datum['state'] == 'present' and not any(l.get('field') == 'location.datum' for l in losses):
        if out['datum']['state'] != 'present' or out['datum']['value'] != datum['value']:
            problems.append(proofs.problem('TRANSFER_READBACK_MISMATCH', 'the output datum differs from the source datum', here + '.datum', expected=datum['value'], found=out['datum']['value']))
    elif out['datum']['state'] != 'absent':
        problems.append(proofs.problem('TRANSFER_READBACK_MISMATCH', 'the source datum is not transferred (absent or declared loss) but the output records one', here + '.datum', found=out['datum']['value']))
    return problems


def row_same(field, a, b):
    """Whether two snapshot rows of one field carry the same typed value (an E3-carried row has no single ``value``)."""
    if a['state'] != b['state']:
        return False
    if a['state'] != 'present':
        return True
    if field == 'location':
        return (a['exactDegrees'] == b['exactDegrees'] and a['datum'] == b['datum']
                and {k: a['height'].get(k) for k in e3proofs.HEIGHT_KEYS} == {k: b['height'].get(k) for k in e3proofs.HEIGHT_KEYS})
    return equal(field, a['value'], b['value'])


def native_number(tokens):
    from decimal import Decimal, InvalidOperation
    try:
        return Decimal(proofs.text_of(tokens)[0])
    except (InvalidOperation, IndexError):
        return None


NATIVE_DATE = re.compile(r'(\d{4})[:-](\d{2})[:-](\d{2})[T ](\d{2}:\d{2}:\d{2})(?:\.(\d+))?(Z|[+-]\d{2}:\d{2})?', re.ASCII)
NATIVE_IPTC_DATE = re.compile(r'(\d{4}):(\d{2}):(\d{2})', re.ASCII)
NATIVE_IPTC_TIME = re.compile(r'(\d{2}:\d{2}:\d{2})(?:\.(\d+))?(Z|[+-]\d{2}:\d{2})?', re.ASCII)


def native_time_carriers(index):
    """``[(carrier, local, offset, fraction)]``: one row for each fixed native carrier whose listing states a capture local time (Exif, XMP exif, XMP photoshop, the IPTC date with its time), each
    row stating only what that carrier itself lists, with ``None`` for a component it does not state. ExifTool spells an Exif and an XMP date alike (``2024:03:01 10:20:30.25+09:00`` for XMP), so both
    are read by one pattern. Exif lists its offset and fraction at their own keys. The IPTC pair is ``IPTC:DateCreated`` (``2024:03:01``) with ``IPTC:TimeCreated`` (``10:20:30+09:00``, the offset
    optional): both must be listed to be a capture time, the offset is the one the time states (never a zone invented for a time without one) and the fraction is whatever the listing states (none for a
    time written as ``HHMMSS``). A ``Z`` is the offset ``+00:00``."""
    def one(key):
        found = by_group1(index, key)
        return proofs.text_of(found)[0] if found else None
    rows = []
    local = one('ExifIFD:DateTimeOriginal')
    if local is not None:
        match = NATIVE_DATE.fullmatch(local)
        rows.append(('exif', '%s-%s-%sT%s' % match.group(1, 2, 3, 4), one('ExifIFD:OffsetTimeOriginal'), one('ExifIFD:SubSecTimeOriginal')) if match else ('exif', local, None, None))
    for key in ('XMP-exif:DateTimeOriginal', 'XMP-photoshop:DateCreated'):
        local = one(key)
        if local is not None:
            match = NATIVE_DATE.fullmatch(local)
            rows.append((key, '%s-%s-%sT%s' % match.group(1, 2, 3, 4), '+00:00' if match.group(6) == 'Z' else match.group(6), match.group(5)) if match else (key, local, None, None))
    date, at_time = one('IPTC:DateCreated'), one('IPTC:TimeCreated')
    if date is not None and at_time is not None:
        day, clock = NATIVE_IPTC_DATE.fullmatch(date), NATIVE_IPTC_TIME.fullmatch(at_time)
        rows.append(('iptc', '%s-%s-%sT%s' % (day.group(1, 2, 3) + (clock.group(1),)), '+00:00' if clock.group(3) == 'Z' else clock.group(3), clock.group(2)) if day and clock else ('iptc', '%s %s' % (date, at_time), None, None))
    return rows


def native_time(index):
    """``(local, offset, fraction)`` of the one capture time the fixed ExifTool listing states across all its carriers; ``None`` if no carrier states a local time.

    The capture time of a photograph is often spread over carriers (the camera's Exif local time, the offset or the fraction restated by IPTC 2:60, XMP photoshop or XMP exif after an editor has
    touched the file). Each component is therefore composed from every carrier independently of the others: the value the carriers that state it agree on, ``None`` when no carrier states it (a zone
    or a fraction is never invented), and, when carriers state different values of one component, the sorted tuple of those values, which never equals a stated value (the planner refuses such a source
    before any write, and an output whose carriers disagree is never a faithful copy). Components are literal: the offset in the ``+HH:MM`` spelling, the fraction as its digits."""
    rows = native_time_carriers(index)
    if not rows:
        return None
    composed = []
    for position in (1, 2, 3):
        stated = sorted({row[position] for row in rows if row[position] is not None})
        composed.append(None if not stated else stated[0] if len(stated) == 1 else tuple(stated))
    return tuple(composed)


def typed_time(time):
    """The JSON form of a composed native time: a component with disagreeing carriers is the list of their values."""
    return [list(c) if isinstance(c, tuple) else c for c in time]


def native_e3_problems(field, source_index, out_index, at):
    """T-native of an E3-carried group: the fixed listing of the source capture against that of the output for the transferred meaning. A capture time is compared as the typed
    (local, offset, fraction) each listing states; a position is compared numerically at the two GPS keys, within the declared quantisation."""
    problems = []
    if field == 'captureTime':
        a, b = native_time(source_index), native_time(out_index)
        torn = lambda time: time is not None and any(isinstance(c, tuple) for c in time)
        if a is not None and (a != b or torn(a) or torn(b)):
            problems.append(proofs.problem('TRANSFER_READBACK_MISMATCH', 'the fixed ExifTool listing of the output states another capture time than that of the source', at + '.native', source=typed_time(a), output=typed_time(b) if b else None))
        return problems, {'native': 'captureTime', 'source': typed_time(a) if a else None}
    compared = []
    for key in ('GPS:GPSLatitude', 'GPS:GPSLongitude'):
        a, b = native_number(by_group1(source_index, key)), native_number(by_group1(out_index, key))
        if a is None or b is None:
            continue
        compared.append(key)
        if abs(a - b) > decimal_bound():
            problems.append(proofs.problem('TRANSFER_READBACK_MISMATCH', 'the fixed ExifTool listing of the output states another coordinate than that of the source beyond the declared quantisation', at + '.native', key=key, source=str(a), output=str(b)))
    return problems, {'native': 'location', 'keys': compared}


def decimal_bound():
    from decimal import Decimal
    return Decimal('0.0000000007')          # half a unit of the 9th decimal (5e-10) plus the 2e-10 serialisation bound


def transfer_proof(plan_, item, payloads_out, record_out, at):
    """Proof T (T-host and T-native) of one written item; returns ``(problems, summary)``."""
    problems = []
    selected = [d['field'] for d in plan_['decisions']]
    out_snap = e4model.snapshot(payloads_out, selected)
    before_snap = e4model.snapshot(item['payloads'], selected)
    src_snap = e4model.snapshot(item['transferSource']['payloads'], selected)
    stray = {}
    if plan_['edit']:
        for name, f in plan_['edit']['fields'].items():
            if f['otherLanguages']['kept']:
                stray[name] = f['otherLanguages']['kept']
    for d in plan_['decisions']:
        field, action = d['field'], d['action']
        row = out_snap[field]
        here = '%s.fields.%s' % (at, field)
        if action == 'write' and field == 'location':
            problems += location_problems(src_snap[field], row, plan_['losses'], here)
            continue
        if action == 'write' and field == 'captureTime':
            wanted = src_snap[field]['value']
            if row['state'] != 'present' or row['value'] != wanted:
                problems.append(proofs.problem('TRANSFER_READBACK_MISMATCH', 'the output captured time differs from the source (local time, offset and fraction, exactly)', here,
                                               expected=wanted, found=row.get('value') if row['state'] == 'present' else row['state']))
            continue
        if action == 'write':
            wanted = src_snap[field]['value']
            found = row['value'] if row['state'] == 'present' else None
            if found is None:
                problems.append(proofs.problem('TRANSFER_READBACK_MISMATCH', 'a transferred field does not read back as present', here, state=row['state']))
            elif e4model.SHAPES[field] == 'langText':
                have = {e['language']: e['text'] for e in found['languages']}
                if found['text'] != wanted['text'] or any(have.get(e['language']) != e['text'] for e in wanted['languages']):
                    problems.append(proofs.problem('TRANSFER_READBACK_MISMATCH', 'the output text or language set differs from the source literal', here, expected=wanted, found=found))
            elif not equal(field, found, wanted):
                problems.append(proofs.problem('TRANSFER_READBACK_MISMATCH', 'the output value differs from the raw source literal', here, expected=jsonable_value(wanted) if not isinstance(wanted, list) else wanted, found=jsonable_value(found) if not isinstance(found, list) else found))
        elif action == 'clear':
            if row['state'] != 'absent':
                problems.append(proofs.problem('TRANSFER_READBACK_MISMATCH', 'a cleared field is not absent in the output', here, state=row['state']))
        else:
            before = before_snap[field]
            same = row_same(field, row, before)
            if not same:
                problems.append(proofs.problem('TRANSFER_READBACK_MISMATCH', 'a field the plan keeps, skips or finds equal changed in the output', here, action=action, before=before['state'], after=row['state']))
    # T-native: the same native key in the source listing and the output listing carries identical tokens
    compared = []
    source_index = item['transferSource']['index']
    out_index = listing.index(record_out)
    written_keys = set()
    if plan_['edit']:
        for name, f in plan_['edit']['fields'].items():
            for dest in f['destinations']:
                if dest['state'] == 'write':
                    written_keys.add(dest['listing'])
    written_keys |= {d['listing'] for x in plan_['extras'] for d in x['destinations'] if d['state'] == 'write'}
    for key in sorted(written_keys):
        a, b = by_group1(source_index, key), by_group1(out_index, key)
        if a and b:
            compared.append(key)
            if proofs.text_of(a) != proofs.text_of(b):
                problems.append(proofs.problem('TRANSFER_READBACK_MISMATCH', 'the fixed ExifTool listing of the output differs from that of the source at the same key', at + '.native', key=key, source=proofs.text_of(a)[:4], output=proofs.text_of(b)[:4]))
    for d in plan_['decisions']:
        if d['field'] in E3_GROUPS and d['action'] == 'write':
            more, summary = native_e3_problems(d['field'], source_index, out_index, at)
            problems += more
            compared.append(summary['native'] + ('' if 'keys' not in summary else ':' + ','.join(summary['keys'])))
    return problems, {'hostFields': len(plan_['decisions']), 'nativeKeysCompared': compared}


# What the independent reader says about an XMP date that the plan itself wrote without an offset or without a fraction: that component is absent, as planned, and carries this typed code.
XMP_ABSENT_COMPONENT = {'offset': 'XMP_NO_OFFSET', 'subSecond': 'XMP_NO_FRACTION'}
LEFT_ALONE = 'a time source the plan leaves alone changed'


def written_xmp_absent_component(found, plan_, item, payloads_out, at):
    """Whether a ``LEFT_ALONE`` problem of the time proof only reports the typed code of a planned absence: an XMP date the plan wrote has no offset or no fraction because the source has none.
    Exactly that and nothing wider: the plan wrote the XMP date at that location, the component was absent without a code before and is absent after with the one code the reader gives that case
    (a component that vanished, or that is present or ambiguous, or an XMP date the plan did not write, stays a mismatch)."""
    if found['message'] != LEFT_ALONE:
        return False
    spec = e3writes.time_groups()['captured']
    reader = records.Record(payloads_out, e3proofs.VIEW)
    for component, code in XMP_ABSENT_COMPONENT.items():
        name = spec[component]
        if found['location'] != '%s.fields.%s.xmp' % (at, name):
            continue
        where = found['source']
        if (spec['local'], 'xmp', where) not in plan_['expect'] or (name, 'xmp', where) in plan_['expect']:
            return False
        before = {(x['family'], x['location']): x for x in item['e3fields'][name]['sources']}.get(('xmp', where))
        after = {(x['family'], x['location']): x for x in reader.field(name)['sources']}.get(('xmp', where))
        return (before is not None and after is not None and (before['state'], before.get('canonical'), before.get('code')) == ('absent', None, None)
                and (after['state'], after.get('canonical'), after.get('code')) == ('absent', None, code))
    return False


def evaluate(p, item, index, data, after_record, out):
    """Outcome of one transfer item from its capture, the written bytes, the fresh native listing of them: proofs P, R, T and N (the E2 proofs, plus T)."""
    from schemaxis.adaptors.exiftool import editing, workbench as wb
    at = '$.items[%d]' % index
    plan_ = item['plan']
    declared = {k for k, v in plan_['declared'].items() if v}
    problems, proof = [], {'P': {}, 'R': {}, 'T': {}, 'N': {}}
    item.update(outputBytes=len(data), outputSha256=legacy.sha(data))
    container = item['container']
    walk_out, container_effects = None, []
    try:
        if item['walk'] is None:
            located_out = e5edit.admit(data, None)
        else:
            walk_out = jpegwrite.walk(data)
            item['outputWalk'] = walk_out
            located_out = containers.locate(data)
        payloads_out = records.Payloads(located_out)
    except (jpegwrite.Refused, containers.Refused) as error:
        out.update(status='failed', fault=wb.fault_dict('OUTPUT_STRUCTURE_INVALID', 'the written file is not a %s that the strict reader admits: %s' % ('JPEG' if walk_out is None and item['walk'] is not None else container.upper() if container != 'jpeg' else 'JPEG', error.message), at + '.image', cause=error.code))
        return out
    if item['walk'] is None:
        item['outputLocated'] = located_out
        thumb_in = thumb_out = None
        result = e5proof.preserve(item['bytes_'], data, allow=e5edit.allowed(item['located'], {'kind': 'location', 'exifTargets': tuple(sorted(exif_scope(plan_)))}))
        problems += [proofs.problem(f['code'], f['message'], at + '.image', path=f['path']) for f in result['faults']]
        container_effects = list(result.get('effects', ()))
        proof['P'] = {'container': container, 'protectedRows': len(item['located']['protected']), 'declaredFamilies': sorted(declared), 'limitations': item['located']['limitations']}
    else:
        found = jpegwrite.preservation(item['walk'], walk_out, item['bytes_'], data, declared)
        problems += [proofs.problem(f['code'], f['message'], at + '.image', **{k: v for k, v in f.items() if k not in ('code', 'message')}) for f in found]
        thumb_in, thumb_out = editing.thumbnail(item['located']), editing.thumbnail(located_out)
        if thumb_in and thumb_in != thumb_out:
            problems.append(proofs.problem('THUMBNAIL_CHANGED', 'the embedded thumbnail bytes differ from the capture', at + '.image'))
        notes_in, notes_out = editing.maker_note_size(item['payloads']), editing.maker_note_size(payloads_out)
        if notes_in is not None and notes_in != notes_out:
            problems.append(proofs.problem('MAKERNOTE_CHANGED', 'the maker note size changed', at + '.image', before=notes_in, after=notes_out))
        tail_in = item['bytes_'][item['walk']['firstScan']:]
        proof['P'] = {'tailSha256': legacy.sha(tail_in), 'tailBytes': len(tail_in), 'scans': walk_out['scans'], 'process': walk_out['frame']['process'], 'declaredSegments': sorted(declared),
                      'renderingSegments': len(jpegwrite.segments_of(walk_out, 'rendering')), 'codingSegments': len(jpegwrite.segments_of(walk_out, 'coding')), 'thumbnail': thumb_out}
    p_problems, problems = problems, []
    # R
    e2 = plan_['edit']
    fields_out = {}
    if e2:
        before_reads, after_reads = {}, {}
        for name, f in e2['fields'].items():
            for d in writes.fields()[name]['destinations']:
                before_reads[(name, d['family'])] = next(x for x in f['destinations'] if x['family'] == d['family'])['before']
                after_reads[(name, d['family'])] = edits.read_destination(payloads_out, d)
        problems += proofs.readback(e2, before_reads, after_reads, at)
        _, fields_out, _ = records.build(located_out, list(e2['fields']), None, catalogue.VERSION_MWG)
        problems += proofs.concordance(e2, fields_out, at)
        problems += proofs.iptc_untouched(e2, item['payloads'], payloads_out, at, extra_touched=iptc_scope(plan_))
    else:
        problems += e3proofs.iptc_nontarget(item['payloads'], payloads_out, iptc_scope(plan_), at)
    if plan_.get('time') or plan_.get('location'):
        problems += e3proofs.xmp_nontarget(item['payloads'], payloads_out, xmp_scope(plan_), at)       # the E3 rule, over the targets of every part
    problems += extras_readback(plan_, payloads_out, at)
    if plan_.get('time'):
        problems += [x for x in e3proofs.time_readback(plan_['time'], item, payloads_out, at) if not written_xmp_absent_component(x, plan_['time'], item, payloads_out, at)]
    if plan_.get('location'):
        problems += e3proofs.location_readback(plan_['location'], payloads_out, at)
    proof['R'] = {'fields': sorted(([*e2['fields']] if e2 else []) + [x['field'] for x in plan_['extras']] + [k for k in ('time', 'location') if plan_.get(k)])}
    targets = exif_scope(plan_)
    exif_in, exif_out = item['located']['exif'], located_out['exif']
    maker_effects = list(container_effects)
    if container not in e5edit.TIFF_LIKE:       # a TIFF/DNG keeps every entry value in its fingerprint rows (proof P)
        found_nontarget = proofs.exif_nontarget(item['payloads'], payloads_out, targets, set(), at, (exif_in[0], exif_out[0]) if len(exif_in) == len(exif_out) == 1 else None, maker_effects)
        problems += e3proofs.exif_problems(found_nontarget) if plan_.get('time') or plan_.get('location') else found_nontarget
    problems += e3proofs.height_problems({'kind': 'location' if plan_.get('location') else 'transfer', 'exifTargets': tuple(tuple(t) for t in (plan_['location'].get('exifTargets', ()) if plan_.get('location') else ()))}, item['payloads'], payloads_out, at)
    # T (reported before R: a transferred value that differs from its source is the transfer's own fault, named before the generic readback code)
    t_problems = []
    if after_record is not None and not after_record['fault']:
        t_problems, proof['T'] = transfer_proof(plan_, item, payloads_out, after_record, at)
    r_problems, problems = t_problems + problems, []
    # N
    record = after_record
    if record is None or record['fault'] or record['warnings'] or record['errors']:
        problems.append(proofs.problem('WRITE_OUTPUT_NATIVE_WARNING', 'ExifTool reports a warning or error for the written file', at + '.native', detail=(record['fault']['message'] if record and record['fault'] else str((record['warnings'] + record['errors'])[:2])[:200] if record else 'no listing')))
    else:
        ctx = {'xmpWritten': plan_['xmpWritten'], 'assignCharset': plan_['iptc']['assignCharset'], 'iptcChanged': plan_['iptc']['changed'], 'digest': plan_['iptc']['digest'],
               'afterIimMd5': proofs.iim_md5(walk_out, data) if walk_out is not None else e5edit.iim_md5(located_out), 'thumbnailSame': thumb_in == thumb_out, 'iptcEmptied': proofs.iptc_emptied(item['payloads'], payloads_out)}
        container_rule = e5edit.side_effect(container, item['located'], located_out) if walk_out is None else None
        location_rule = e3proofs.extra_side_effect(plan_['location']) if plan_.get('location') else None
        if container_rule or location_rule:
            ctx['extra'] = lambda key, a, b: (location_rule(key, a, b) if location_rule else None) or (container_rule(key, a, b) if container_rule else None)
        before_record = item['beforeRecord']
        names_ = [*e2['fields']] if e2 else []
        reader_fields = {**fields_out}
        if e2:
            checked, mismatches = listing.anchors(item, fields_out, {'image': listing.index(record), 'sidecar': None})
            if mismatches:
                problems.append(proofs.problem('NATIVE_ANCHOR_MISMATCH', 'ExifTool and the independent reader disagree about the written file', at + '.native', mismatches=mismatches[:listing.ANCHOR_REPORT]))
        _, view_mismatches = anchor_fields(payloads_out, [d['field'] for d in plan_['decisions']], listing.index(record))
        if view_mismatches:
            problems.append(proofs.problem('NATIVE_ANCHOR_MISMATCH', 'ExifTool and the independent reader disagree about the written file', at + '.native', mismatches=view_mismatches[:listing.ANCHOR_REPORT]))
        diff = proofs.native_diff(before_record, record, e2 or {'fields': {}}, ctx, extra_targets=native_targets(plan_))
        if diff['unexplained']:
            problems.append(proofs.problem('NATIVE_UNEXPLAINED_CHANGE', 'a native key changed that is neither a target of the plan nor a declared side effect', at + '.native', changes=diff['unexplained'][:8]))
        item['outputNativeGroups'] = editing.native_groups(record)
        proof['N'] = {'targets': diff['targets'], 'sideEffects': diff['sideEffects'] + maker_effects, 'renumbered': diff['renumbered'], 'unexplained': len(diff['unexplained']),
                      'keysBefore': len(editing.native_keys(before_record)), 'keysAfter': len(editing.native_keys(record))}
    problems = r_problems + p_problems + problems     # metadata first: a wrong value is reported before an integrity fault
    proof['problems'] = len(problems)
    if problems:
        first = problems[0]
        out.update(status='failed', fault=wb.fault_dict(first['code'], first['message'], first['location'], problems=problems[:8]), proofs=None)
    else:
        out.update(status='written', proofs=proof)
    return out


# ---------------------------------------------------------------- publications
def names(p):
    return [PLAN_FILE, REPORT_FILE, 'manifest.json']


def row_extra(p, item, outcome):
    plan_ = item['plan']
    return {'outcome': plan_['outcome'], 'transferSource': plan_['source'], 'decisions': plan_['decisions'], 'losses': plan_['losses'],
            'extras': [{'field': x['field'], 'action': x['action'], 'destinations': [{k: v for k, v in d.items() if k in ('family', 'write', 'state', 'reason')} for d in x['destinations']]} for x in plan_['extras']],
            'e2Fields': sorted(plan_['edit']['fields']) if plan_['edit'] else []}


def entry_of(item):
    entry = {'id': item['id'], 'captureSha256': item.get('sha256'), 'arguments': []}
    plan_ = item.get('plan')
    if item['status'] != 'ok' or plan_ is None:
        entry.update(status='refused', outcome='refused', fault=item.get('fault'))
        return entry
    entry.update(status='planned', outcome=plan_['outcome'], arguments=list(plan_['args']), source=plan_.get('source') or plan_.get('transferSource'), decisions=plan_['decisions'], losses=plan_['losses'])
    if 'quantisation' in plan_:
        entry['quantisation'] = plan_['quantisation']
    return entry


def documents(p, ctx, base, table, items, outcomes, encode):
    plan_doc = {**base, 'version': PLAN_SCHEMA, 'source': p['source'], 'transfer': p['transfer'], 'policies': p['policies'], 'items': [entry_of(i) for i in items],
                'statement': 'The typed values each destination receives, decided from independent snapshots of the source and the destination before any native write; values are chosen by Schemaxis and never authored as native options.'}
    if ctx.external is not None:
        plan_doc['sourceCapture'] = {k: ctx.external['record'][k] for k in ('sha256', 'bytes')}
    report = {**base, 'items': table, 'statement': 'Per-item outcomes with the proofs R, P, T and N. T compares the raw source literal and the fixed native listings key by key; P is about bytes, not pixels.',
              'review': {'observedMetadataOnly': True, 'privacyCertified': False, 'humanReviewRequired': True}, 'losses': LOSSES}
    return {PLAN_FILE: encode(plan_doc), REPORT_FILE: encode(report)}
