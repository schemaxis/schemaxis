"""Time and location write family: correctTime, setLocation and geotagFromTrack (host-only planning; the writer is the E2 copy writer).

Each operation turns declared domain intent (device clock references and corrections, positions, GPX tracks) into one explicit plan per captured item,
decided from the independent readers before any native process starts. The native write, the three proofs (readback R, preservation P, closed native
diff N), the stable per-item artifact slots, truthful partial outcomes and offline verification are the E2 copy writer's; this module supplies the plans, the
proof expectations for time and location targets, and the plan, report and residual documents.

Nothing here accepts a native tag, flag, configuration, expression or catalogue identity: the operation selects the internal expanded catalogue view, and
every native assignment is a group-qualified name from ``writes-3.json`` with a value Schemaxis computed. A plan can be published without writing
(``apply: plan``) and applied later; the applied plan's inputs are recomputed, never trusted, and a changed capture or an edited value is refused.
"""
from decimal import Decimal
from fractions import Fraction
import json
import re

from schemaxis.adaptors.exiftool import catalogue, clockmodel, e3place, e5edit, e3read, e3reports, e3time, e3track, e3writes, edits, locations, listing, mediaset, records, timecalc as tc
from schemaxis.errors import fail

OPERATIONS = ('correctTime', 'setLocation', 'geotagFromTrack')
PLAN_SCHEMAS = {'correctTime': 'schemaxis.exiftool.time-correction/1', 'setLocation': 'schemaxis.exiftool.location/1', 'geotagFromTrack': 'schemaxis.exiftool.geotag/1'}
PLAN_FILES = {'correctTime': 'time-correction-plan.json', 'setLocation': 'location-plan.json', 'geotagFromTrack': 'geotag-plan.json'}
VIEW = catalogue.VERSION_E3
IDENTIFIER = re.compile(r'[A-Za-z][A-Za-z0-9_]{0,31}')
TIME_POLICY_DEFAULTS = {'sourceConflicts': 'refuse', 'subSecond': 'addIfNeeded', 'uncorrectedItems': 'copyUnchanged'}
TIME_POLICY_VALUES = {'sourceConflicts': ('refuse', 'preferFamily'), 'preferFamily': ('exif', 'xmp', 'iptc'), 'subSecond': ('addIfNeeded', 'refuse'), 'uncorrectedItems': ('copyUnchanged', 'refuseSlot')}
LOCATION_POLICY_KEYS = ('staleCompanions', 'xmp', 'createExif', 'altitudeNotExpressible', 'removeDirection', 'uncorrectedItems')
GEOTAG_POLICY_KEYS = LOCATION_POLICY_KEYS + ('gpsStamp', 'maxSpeedMetersPerSecond')
MAX_POSITIONS = mediaset.MAX_ITEMS


# ---------------------------------------------------------------- static planning (document only; no file is read)
def policies_of(op, given):
    """The effective policies of a write operation with every default explicit; an unknown value is refused at its ``$`` location."""
    given = dict(given or {})
    if op == 'correctTime':
        out = dict(TIME_POLICY_DEFAULTS)
        for key, value in given.items():
            if value not in TIME_POLICY_VALUES[key]:
                fail('INVALID_ARGUMENT', 'policy %s accepts %s' % (key, ', '.join(TIME_POLICY_VALUES[key])), '$.policies.' + key)
            out[key] = value
        if 'preferFamily' in out and out['sourceConflicts'] != 'preferFamily':
            fail('INVALID_ARGUMENT', 'preferFamily needs sourceConflicts: preferFamily', '$.policies.preferFamily')
        if out['sourceConflicts'] == 'preferFamily' and 'preferFamily' not in out:
            fail('INVALID_ARGUMENT', 'sourceConflicts: preferFamily names the family to prefer (exif, xmp or iptc)', '$.policies.preferFamily')
        return out
    allowed = LOCATION_POLICY_KEYS if op == 'setLocation' else GEOTAG_POLICY_KEYS
    out = {k: e3place.POLICY_DEFAULTS[k] for k in allowed if k in e3place.POLICY_DEFAULTS}
    for key, value in given.items():
        if key not in allowed:
            fail('UNKNOWN_ARGUMENT', 'policy %s does not apply to %s' % (key, op), '$.policies.' + key)
        if key == 'removeDirection':
            if not isinstance(value, bool):
                fail('INVALID_ARGUMENT', 'removeDirection is true or false', '$.policies.removeDirection')
        elif key == 'maxSpeedMetersPerSecond':
            e3reports.tolerance_text(value, '$.policies.maxSpeedMetersPerSecond', maximum=1000)
        elif value not in e3place.POLICY_VALUES[key]:
            fail('INVALID_ARGUMENT', 'policy %s accepts %s' % (key, ', '.join(e3place.POLICY_VALUES[key])), '$.policies.' + key)
        out[key] = value
    return out


def static_plan(op, p, media, document=None):
    """The effective operation block of a write operation. ``p`` is the validated argument dict; ``planFile`` alone selects plan application."""
    given = set(p) - {'media', 'apply', 'plan'}
    if 'plan' in p:
        if given:
            fail('INVALID_ARGUMENT', 'a plan carries every other input of its operation; give only media, apply and plan', '$.plan', also=sorted(given))
        if not p['plan'].startswith('/') or '\0' in p['plan']:
            fail('INVALID_PHOTO_SOURCE', 'select an absolute local plan file path', '$.plan')
        return {'planFile': p['plan']}
    if op == 'geotagFromTrack' and 'tracks' not in p:
        fail('MISSING_ARGUMENT', 'name at least one GPX track', '$.tracks')
    if op == 'correctTime':
        return static_time(p, media)
    if op == 'setLocation':
        return static_location(p, media)
    return static_geotag(p, media)


def shift_text(value, at):
    try:
        return {'seconds': tc.seconds_text(tc.duration_ns(value, at))}
    except tc.TimeProblem as error:
        fail(error.code, error.message, at)


def static_time(p, media):
    ids = [i['id'] for i in media['items']] if media['kind'] == 'items' else None
    time = e3reports.plan_reconcile(p, media)
    corrections, seen = [], set()
    if not p.get('corrections'):
        fail('INVALID_ARGUMENT', 'name at least one correction (a group with from: references, a shift or a setOffset)', '$.corrections')
    declared = None if time['groups']['by'] != 'declared' else {m['group'] for m in time['groups']['members']}
    for index, entry in enumerate(p['corrections']):
        at = '$.corrections[%d]' % index
        if not IDENTIFIER.fullmatch(entry['group']):
            fail('GROUP_MEMBERSHIP_INVALID', 'a group id is an ASCII letter followed by up to 31 letters, digits or underscores', at + '.group', value=entry['group'][:64])
        if entry['group'] in seen:
            fail('INVALID_ARGUMENT', 'a group has more than one correction entry', at + '.group', value=entry['group'])
        seen.add(entry['group'])
        if declared is not None and entry['group'] not in declared:
            fail('GROUP_MEMBERSHIP_INVALID', 'the correction names a group that is not declared', at + '.group', value=entry['group'][:64], groups=sorted(declared)[:20])
        if entry.get('from') is not None and 'shift' in entry:
            fail('INVALID_ARGUMENT', 'give either from: references or a shift, not both', at)
        if entry.get('from') is None and 'shift' not in entry and 'setOffset' not in entry:
            fail('INVALID_ARGUMENT', 'a correction needs from: references, a shift or a setOffset', at)
        out = {'group': entry['group']}
        if entry.get('from') is not None:
            out['from'] = entry['from']
        if 'shift' in entry:
            out['shift'] = shift_text(entry['shift'], at + '.shift')
        if 'setOffset' in entry:
            try:
                tc.parse_offset(entry['setOffset']['offset'], at + '.setOffset.offset')
            except tc.TimeProblem as error:
                fail('INVALID_ARGUMENT', error.message, at + '.setOffset.offset')
            out['setOffset'] = {'offset': entry['setOffset']['offset'], 'keep': entry['setOffset']['keep']}
        corrections.append(out)
    fields = [g for g in e3writes.TIME_GROUPS if g in p.get('timeFields', list(e3time.DEFAULT_GROUPS))]
    if not fields:
        fail('INVALID_ARGUMENT', 'select at least one time field', '$.timeFields')
    return {'time': time, 'corrections': corrections, 'timeFields': fields, 'policies': policies_of('correctTime', p.get('policies'))}


def normal_request(spec, at, default=False):
    """The echoed, validated form of one position request (decimals as text). Authored values are checked with the same parser the run uses."""
    e3place.parse_entry(spec, None, at)
    out = {'latitude': spec['latitude'] if isinstance(spec['latitude'], str) else repr(spec['latitude']), 'longitude': spec['longitude'] if isinstance(spec['longitude'], str) else repr(spec['longitude'])}
    for key in ('altitude', 'datum', 'horizontalErrorMeters', 'gpsUtc'):
        if spec.get(key) is not None:
            out[key] = dict(spec[key]) if key == 'altitude' else spec[key]
    return out


def static_location(p, media):
    if not p.get('positions') and 'default' not in p:
        fail('INVALID_ARGUMENT', 'give positions and/or a default position', '$.positions')
    ids = [i['id'] for i in media['items']] if media['kind'] == 'items' else None
    positions, seen = [], set()
    for index, entry in enumerate(p.get('positions', [])):
        at = '$.positions[%d]' % index
        if ids is not None and entry['item'] not in ids:
            fail('UNKNOWN_ITEM', 'the position names an item that is not in media.items', at + '.item', value=entry['item'][:64], items=ids[:20])
        if entry['item'] in seen:
            fail('INVALID_ARGUMENT', 'an item has more than one position entry', at + '.item', value=entry['item'])
        seen.add(entry['item'])
        positions.append({'item': entry['item'], **normal_request(entry, at)})
    default = normal_request(p['default'], '$.default', True) if 'default' in p else None
    return {'positions': positions, 'default': default, 'policies': policies_of('setLocation', p.get('policies'))}


def static_geotag(p, media):
    tracks, seen = [], set()
    for index, track in enumerate(p['tracks']):
        at = '$.tracks[%d]' % index
        if not IDENTIFIER.fullmatch(track['id']):
            fail('INVALID_ARGUMENT', 'a track id is an ASCII letter followed by up to 31 letters, digits or underscores', at + '.id', value=track['id'][:64])
        if track['id'] in seen:
            fail('INVALID_ARGUMENT', 'track ids are unique', at + '.id', value=track['id'])
        seen.add(track['id'])
        path = track['path']
        if not path.startswith('/') or '\0' in path or '..' in path.split('/'):
            fail('INVALID_ARGUMENT', 'select an absolute local track path without parent references', at + '.path')
        if 'sha256' in track and not re.fullmatch(r'[0-9a-f]{64}', track['sha256']):
            fail('INVALID_SHA256', 'use 64 lowercase hexadecimal digits', at + '.sha256')
        tracks.append({k: track[k] for k in ('id', 'path', 'sha256') if k in track})
    photo = p.get('photoTime') or {}
    correction = photo.get('clockCorrection', 'none')
    block_correction = 'none'
    if isinstance(correction, dict):
        if ('shifts' in correction) == ('plan' in correction):
            fail('INVALID_ARGUMENT', 'clockCorrection is none, shifts or a plan', '$.photoTime.clockCorrection')
        if 'plan' in correction:
            if not correction['plan'].startswith('/') or '\0' in correction['plan']:
                fail('INVALID_PHOTO_SOURCE', 'select an absolute local plan file path', '$.photoTime.clockCorrection.plan')
            block_correction = {'plan': correction['plan']}
        else:
            block_correction = {'shifts': [{'group': s['group'], 'shift': shift_text(s['shift'], '$.photoTime.clockCorrection.shifts[%d].shift' % i)} for i, s in enumerate(correction['shifts'])]}
    offsets = []
    for index, entry in enumerate(photo.get('assumedOffsets', [])):
        try:
            tc.parse_offset(entry['offset'], '$.photoTime.assumedOffsets[%d].offset' % index)
        except tc.TimeProblem as error:
            fail('INVALID_ARGUMENT', error.message, '$.photoTime.assumedOffsets[%d].offset' % index)
        offsets.append({'group': entry['group'], 'offset': entry['offset']})
    groups = p.get('groups') or {'by': 'recordedDevice'}
    time = e3reports.plan_reconcile({'groups': groups, 'assumedOffsets': offsets}, media)
    interpolation = {**e3track.DEFAULTS, **p.get('interpolation', {})}
    e3reports.tolerance_text(interpolation['overlapAgreementMeters'], '$.interpolation.overlapAgreementMeters', maximum=1000)
    track = {**e3track.TRACK_DEFAULTS, **p.get('track', {})}
    elevation = track['elevation']
    if isinstance(elevation, dict) and elevation.get('reference') not in ('seaLevel', 'ellipsoidal'):
        fail('INVALID_ARGUMENT', 'declare what the logger recorded: reference seaLevel or ellipsoidal', '$.track.elevation.reference')
    if 'datum1_0' in track:
        try:
            locations.parse_datum(track['datum1_0'], '$.track.datum1_0')
        except locations.LocationProblem as error:
            fail(error.code, error.message, '$.track.datum1_0')
    return {'tracks': tracks, 'photoTime': {'source': 'captured', 'assumedOffsets': offsets, 'clockCorrection': block_correction}, 'groups': time['groups'], 'interpolation': interpolation,
            'track': track, 'policies': policies_of('geotagFromTrack', p.get('policies'))}


def describe(op):
    """Publication strings of the three operations."""
    return PLAN_SCHEMAS[op], PLAN_FILES[op]


# ---------------------------------------------------------------- captured inputs and the set-level context (run and verify build the same context from retained bytes)
def arguments_of(p):
    """The validated authored arguments of an operation, the recomputable inputs a published plan carries (media, apply and plan excluded)."""
    return p['e3'].get('arguments')


def load_plan_document(data, op, at):
    """A published plan parsed against its closed schema; anything else is a set-level ``PLAN_INVALID`` / ``PLAN_CATALOGUE_UNKNOWN``."""
    try:
        doc = json.loads(data.decode('utf-8'), object_pairs_hook=unique_pairs)
    except (UnicodeDecodeError, ValueError, RecursionError) as error:
        fail('PLAN_INVALID', 'the plan is not strict UTF-8 JSON: ' + str(error)[:120], at)
    schema = PLAN_SCHEMAS[op]
    if not isinstance(doc, dict) or doc.get('version') != schema or doc.get('operation') != op:
        fail('PLAN_INVALID', 'the document is not a %s plan' % op, at, expected=schema)
    expected = {'catalogue': {'version': VIEW, 'sha256': catalogue.digest(VIEW)}, 'writes': {'version': e3writes.VERSION, 'sha256': e3writes.digest()}}
    for key, value in expected.items():
        if doc.get(key) != value:
            fail('PLAN_CATALOGUE_UNKNOWN', 'the plan names a %s identity this code does not know; a plan never selects data or code' % key, at + '.' + key, named=str(doc.get(key))[:120])
    if not isinstance(doc.get('inputs'), dict) or not isinstance(doc.get('items'), list) or not isinstance(doc.get('declared'), dict):
        fail('PLAN_INVALID', 'the plan lacks its inputs, declared block or item list', at)
    for index, entry in enumerate(doc['items']):
        if not isinstance(entry, dict) or not isinstance(entry.get('id'), str) or not isinstance(entry.get('captureSha256'), str) or not isinstance(entry.get('arguments'), list):
            fail('PLAN_INVALID', 'a plan item lacks its id, capture hash or arguments', '%s.items[%d]' % (at, index))
    return doc


def unique_pairs(items):
    if len({k for k, _ in items}) != len(items):
        raise ValueError('duplicate JSON key')
    return dict(items)


def effective_block(p, media, doc=None):
    """The static block the run uses: the document's own, or the one recomputed from a published plan's recorded inputs (which must reproduce its declared block)."""
    block = p['e3']
    if 'planFile' not in block:
        return block
    op = p['operation']
    from schemaxis.core.declarations import validate_arguments
    from schemaxis.adaptors.exiftool import options
    arguments = doc['inputs']
    try:
        checked = validate_arguments({k: v for k, v in options.WRITE_OPTIONS[op].items() if k not in ('media', 'apply', 'plan')}, arguments)
    except Exception as error:
        fail('PLAN_INVALID', 'the recorded inputs of the plan are not valid for %s' % op, '$.plan', cause=str(getattr(error, 'fault', error))[:200])
    block2 = static_plan(op, checked, media)
    block2['arguments'] = json_safe(checked)
    if json_safe(block2) != doc['declared']:
        fail('PLAN_INCONSISTENT', 'the declared block of the plan differs from the one its recorded inputs produce', '$.plan.declared')
    return {**block2, 'planFile': block['planFile']}


def json_safe(value):
    """A JSON-stable deep copy (tuples become lists, mappings keep their keys)."""
    return json.loads(json.dumps(value, sort_keys=True))


def capture(p, directory, media):
    """Capture the declared plan and track files into ``inputs/`` (run time only); returns the ``inputs`` record of ``captures.json`` (``{}`` for none)."""
    block = p['e3']
    inputs = {}
    doc = None
    if 'planFile' in block:
        (directory / e3track.INPUTS).mkdir(exist_ok=True)
        data = e3track.capture_bytes(block['planFile'], e3track.PLAN_BYTES, 'PLAN_UNREADABLE', '$.plan')
        (directory / e3track.PLAN_FILE).write_bytes(data)
        import hashlib
        inputs['plan'] = {'source': block['planFile'], 'file': e3track.PLAN_FILE, 'sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data)}
        doc = load_plan_document(data, p['operation'], '$.plan')
    eff = effective_block(p, media, doc)
    if p['operation'] == 'geotagFromTrack':
        tracks = [dict(t) for t in eff['tracks']]
        if doc is not None:
            recorded = {t['id']: t['sha256'] for t in doc.get('trackSha256', [])}
            for track in tracks:
                if track['id'] in recorded:
                    track['sha256'] = recorded[track['id']]
        wrapper = {**p, 'e3': {**eff, 'tracks': tracks}}
        inputs.update(e3track.capture_inputs(wrapper, directory))
        correction = eff['photoTime']['clockCorrection']
        if isinstance(correction, dict) and 'plan' in correction:
            wrapper = {**p, 'e3': {'clockPlanFile': correction['plan']}}
            inputs.update(e3track.capture_inputs(wrapper, directory))
            if doc is not None and doc.get('clockPlanSha256') and inputs['clockPlan']['sha256'] != doc['clockPlanSha256']:
                fail('CLOCK_PLAN_HASH_MISMATCH', 'the clock-correction plan bytes differ from the plan this geotag plan recorded', '$.plan.clockPlanSha256', observed=inputs['clockPlan']['sha256'])
    return inputs


class Context:
    """Everything an operation needs beyond one item, rebuilt identically at run time and in verification from the retained run directory."""

    def __init__(self, p, directory, captured):
        self.p, self.op = p, p['operation']
        self.inputs = captured.get('inputs', {})
        self.plan_doc = self.clock_plan = None
        self.plan_sha = None
        media = p['media']
        if 'plan' in self.inputs:
            self.plan_doc = load_plan_document(read_retained(directory, self.inputs['plan']), self.op, '$.plan')
            self.plan_sha = self.inputs['plan']['sha256']
        self.block = effective_block(p, media, self.plan_doc)
        self.tracks = self.index = None
        if self.op == 'geotagFromTrack':
            self.tracks = e3track.parse_tracks(directory, self.inputs, self.block)
            self.index = e3track.span_index(self.tracks, self.block)
            if 'clockPlan' in self.inputs:
                self.clock_plan = load_plan_document(read_retained(directory, self.inputs['clockPlan']), 'correctTime', '$.photoTime.clockCorrection.plan')

    @property
    def policies(self): return self.block['policies']


def read_retained(directory, record):
    import hashlib
    data = (directory / record['file']).read_bytes()
    if hashlib.sha256(data).hexdigest() != record['sha256'] or len(data) != record['bytes']:
        fail('CAPTURE_CHANGED', 'a retained captured input differs from its capture record', record['file'])
    return data


def input_names(captured):
    """Retained evidence names of the captured plan and track files."""
    out = set()
    for key in ('plan', 'clockPlan'):
        if key in captured.get('inputs', {}):
            out.add(captured['inputs'][key]['file'])
    out |= {t['file'] for t in captured.get('inputs', {}).get('tracks', [])}
    return out


# ---------------------------------------------------------------- per-item planning
def field_names(p):
    op = p['operation']
    if op == 'correctTime':
        return e3read.field_names('reconcileTime')
    if op == 'setLocation':
        return e3read.field_names('locate')
    return sorted(set(e3read.field_names('reconcileTime')) | set(e3read.field_names('locate')), key=list(catalogue.fields(VIEW)).index)


def native_input_problems(record):
    if record['fault']:
        return (record['fault']['code'], record['fault']['message'])
    if record['warnings'] or record['errors']:
        return ('WRITE_INPUT_NATIVE_WARNING', 'ExifTool reports a warning or error for the capture, so it is not rewritten: ' + str((record['warnings'] + record['errors'])[0])[:160])
    return None


def prepare(items, before, names):
    """Per ok item: the E3 field records (independent), anchored against the native before listing; refusals turn the item into a refused outcome."""
    for item in items:
        if item['status'] != 'ok':
            continue
        try:
            record = before[item['file']]
            problem = native_input_problems(record)
            if problem:
                raise edits.Refusal(problem[0], problem[1])
            reader = records.Record(item['payloads'], VIEW)
            fields = {name: reader.field(name) for name in names}
            checked, mismatches = listing.anchors(item, fields, {'image': listing.index(record), 'sidecar': None})
            if mismatches:
                raise edits.Refusal('NATIVE_ANCHOR_MISMATCH', 'ExifTool and the independent reader disagree about this capture, so it is not rewritten', item['file'], count=len(mismatches), mismatches=mismatches[:listing.ANCHOR_REPORT])
            item['e3fields'] = fields
            item['e3anchors'] = checked
        except edits.Refusal as error:
            refused(item, error)


def refused(item, error):
    from schemaxis.adaptors.exiftool import workbench as wb
    item.update(status='refused', fault=wb.fault_dict(error.code, error.message, item['file'] if error.location in ('$', None) else error.location, **error.observed), plan=None, args=None)


def unchanged_plan(reason, detail=None):
    return {'kind': 'unchanged', 'outcome': 'unchanged', 'reason': reason, 'detail': dict(detail or {}), 'args': [], 'declared': {'xmp': False, 'iptc': False, 'exif': False, 'exifCreate': False},
            'iptc': {'assignCharset': False, 'changed': False, 'digest': False, 'state': 'unchanged', 'charset': None, 'created': False}, 'xmpWritten': False, 'infos': [], 'losses': []}


def unchanged(item, reason, detail=None):
    """An item that needs no write: its published slot is a byte-identical copy of the capture (a declared outcome with its reason)."""
    item['plan'] = unchanged_plan(reason, detail)
    item['args'] = []


def apply_uncorrected(items, policies):
    """``uncorrectedItems: refuseSlot`` turns every unchanged item into a truthful outcome document instead of a copy."""
    if policies.get('uncorrectedItems') != 'refuseSlot':
        return
    for item in items:
        if item['status'] == 'ok' and item['plan']['kind'] == 'unchanged':
            refused(item, edits.Refusal('ITEM_UNCHANGED', 'nothing is written for this item (%s) and the policy publishes no copy' % item['plan']['reason'], '$', reason=item['plan']['reason'], detail={k: v for k, v in item['plan']['detail'].items() if isinstance(v, (str, int))}))


def check_plan_application(ctx, item):
    """A published plan applies to a capture only if the capture is the one it was made for (``PLAN_STALE``) and its recorded arguments are reproduced (``PLAN_INCONSISTENT``)."""
    if ctx.plan_doc is None:
        return None
    entry = next((e for e in ctx.plan_doc['items'] if e['id'] == item['id']), None)
    if entry is None or entry['captureSha256'] != item['sha256']:
        raise edits.Refusal('PLAN_STALE', 'the capture is not the file this plan was made for (a different byte, or an item the plan does not list)', '$.plan', item=item['id'], planned=None if entry is None else entry['captureSha256'], captured=item['sha256'])
    return entry


def finish_item(ctx, item, entry):
    if entry is not None:
        recomputed = item['plan']['args']
        if recomputed != entry['arguments'] or item['plan']['outcome'] != entry.get('outcome', item['plan']['outcome']):
            raise edits.Refusal('PLAN_INCONSISTENT', 'the arguments this plan records are not what its own recorded inputs produce for this capture', '$.plan', item=item['id'], recorded=entry['arguments'][:6], recomputed=recomputed[:6])


def plan_items(p, items, before, ctx):
    """Plan every ok item of an E3 write operation (set-level analysis first); refusals are per item and the others continue."""
    prepare(items, before, field_names(p))
    {'correctTime': plan_time_items, 'setLocation': plan_location_items, 'geotagFromTrack': plan_geotag_items}[p['operation']](p, items, ctx)
    apply_uncorrected(items, ctx.policies)


def xmp_after(item):
    return item['payloads'].xmp[0] != 'absent'


def iptc_block(item, writes):
    from schemaxis.adaptors.exiftool import proofs
    changed = bool(writes)
    if item['walk'] is None:       # a container: the IPTC digest is judged by the container's own guards (TIFF/DNG never assign it; PNG, WebP and HEIF have no IPTC)
        digest_before = e5edit.digest_present(item['located'])
    else:
        digest_before = 0x0425 in proofs.iim_resources(item['walk'], item['bytes_'])
    context = edits.iim_context(item['payloads'])
    return {'state': context['state'], 'charset': context.get('charset'), 'assignCharset': False, 'changed': changed, 'created': False, 'digest': bool(changed and (xmp_after(item) or digest_before)) and item['walk'] is not None}


def decide(ctx, item, build):
    """Run one item's planner under the plan-application checks; a Refusal becomes the item's outcome."""
    try:
        entry = check_plan_application(ctx, item)
        build()
        if item['plan'] is not None:
            e5edit.write_guards(item, item['plan'])
            finish_item(ctx, item, entry)
    except edits.Refusal as error:
        refused(item, error)


def plan_time_items(p, items, ctx):
    block = ctx.block
    ok = [i for i in items if i['status'] == 'ok']
    records_ = [e3read.time_record(i['id'], i['e3fields']) for i in ok]
    try:
        report, exact = clockmodel.reconcile_exact(records_, block['time'], [i['id'] for i in items if i['status'] != 'ok'])
    except clockmodel.ClockProblem as error:
        e3reports.clock_problem(error)
    item_ids = {g['id'] for g in report['groups']}
    for index, correction in enumerate(block['corrections']):
        if correction['group'] not in item_ids:
            fail('GROUP_MEMBERSHIP_INVALID', 'the correction names a group that does not exist in this media set', '$.corrections[%d].group' % index, value=correction['group'][:64], groups=sorted(item_ids)[:20])
    by_group = {c['group']: c for c in block['corrections']}
    assumed = {a['group']: tc.parse_offset(a['offset']) for a in block['time']['assumedOffsets']}
    ctx.report, ctx.exact = report, exact
    for item in ok:
        decide(ctx, item, lambda item=item: time_item(ctx, item, exact[item['id']], by_group, assumed))


def time_item(ctx, item, ex, by_group, assumed):
    block = ctx.block
    at = item['file']
    correction = by_group.get(ex['group'])
    if ex['group'] is None:
        return unchanged(item, 'DEVICE_IDENTITY_UNRESOLVED')
    if correction is None:
        return unchanged(item, 'noCorrectionForGroup', {'group': ex['group']})
    delta, skew_text, basis = 0, None, 'shift'
    if correction.get('from') == 'references':
        basis = 'references'
        if ex['groupState'] == 'conflicting':
            raise edits.Refusal('GROUP_CONFLICTING', 'the references of this device group disagree beyond the tolerance, so nothing is corrected from them', at, group=ex['group'])
        if ex['outside']:
            raise edits.Refusal('outsideReferenceSpan', 'the recorded instant lies outside the span of the drift references by more than the declared allowance', at, group=ex['group'])
        if ex['groupState'] != 'anchored':
            raise edits.Refusal('GROUP_NOT_ANCHORED', 'the device group is %s: no declared reference or simultaneity assertion anchors its clock' % ex['groupState'], at, group=ex['group'])
        if ex['recordedInstant'] is None:       # no recorded instant (no recorded or assumed offset): only a constant wall-clock skew applies, never an instant skew or a drift intercept
            skew = None if ex.get('model') == 'linearDrift' else ex['wallSkew']
        else:
            skew = ex['skew']
        if skew is None:
            raise edits.Refusal('OFFSET_UNKNOWN', 'the item has no recorded instant and the references give no constant wall-clock skew for it (a drift skew needs the instant)', at, group=ex['group'])
        delta, skew_text = -clockmodel.round_ns(skew), clockmodel.text(skew)
    elif 'shift' in correction:
        delta = tc.seconds_ns(correction['shift']['seconds'])
    item['plan'] = time_plan(block, item, ex['group'], correction, delta, skew_text, basis, assumed.get(ex['group']), at)
    item['args'] = item['plan']['args']


def set_offset_of(correction):
    if 'setOffset' not in correction:
        return None
    return {'minutes': tc.parse_offset(correction['setOffset']['offset']), 'keep': correction['setOffset']['keep']}


def time_plan(block, item, group_id, correction, delta, skew_text, basis, assumed_offset, at, absolute=None):
    """The plan of one item's time correction for a device group, given the exact wall-clock move ``delta`` the correction declares (never writes to the item).

    ``correctTime`` plans an item with it, and ``geotagFromTrack`` recomputes a published clock-correction entry with it from the same capture and the plan's own
    recorded inputs, so a contradictory plan is found by the planner that produced it rather than by a second, partial, set of rules.
    """
    set_offset = set_offset_of(correction)
    group_plans = []
    for group in block['timeFields']:
        gp = e3time.plan_group(group, item['e3fields'], item['payloads'], delta, set_offset, assumed_offset, block['policies'], at, absolute)
        if gp is not None:
            group_plans.append(gp)
    if not group_plans:
        return unchanged_plan('noTimeFieldPresent', {'group': group_id})
    changed = [gp for gp in group_plans if gp['changed']]
    if not changed:
        return unchanged_plan('zeroNetChange', {'group': group_id})
    for gp in changed:
        for t in gp['targets']:
            if t['family'] == 'exif' and (t['changes'] or t.get('forced')) and t['location'].startswith('ExifIFD:') and not e3time.exif_ifd_exists(item['payloads']):
                raise edits.Refusal('EXIF_CREATION_UNVERIFIED', 'the correction would create an ExifIFD, which the native writer fills with an ExifVersion and other mandatory values; no time write creates one', at, location=t['location'])
    args = e3time.assignments(group_plans)
    xmp_props = {t['location'] for gp in changed for t in gp['targets'] if t['family'] == 'xmp' and t['changes']}
    problem = e3place.xmp_qualifier_problem(item['located'], xmp_props)
    if problem:
        raise edits.Refusal('XMP_QUALIFIERS_WOULD_BE_LOST', 'an XMP value this correction rewrites carries qualifiers that the rewrite would silently drop, so the item is refused rather than flattened', at, **problem)
    writes = [(n, v) for gp in changed for t in gp['targets'] if (t['changes'] or t.get('forced')) and t['family'] == 'iptc' for n, v in t['writes']]
    exif = any(t['family'] == 'exif' and t['changes'] for gp in changed for t in gp['targets'])
    iptc = iptc_block(item, writes)
    if iptc['digest']:
        args.append('-Photoshop:IPTCDigest=new')
    native = sorted({w for gp in changed for t in gp['targets'] if (t['changes'] or t.get('forced')) for w, _ in t['writes']})
    return {'kind': 'time', 'outcome': 'corrected', 'group': group_id, 'basis': basis, 'skewSeconds': skew_text, 'groups': group_plans, 'args': args, 'expect': e3time.expectations(group_plans),
            'declared': {'xmp': bool(xmp_props), 'iptc': iptc['changed'], 'exif': exif, 'exifCreate': False}, 'iptc': iptc, 'xmpWritten': bool(xmp_props), 'nativeTargets': native,
            'infos': sorted({i for gp in group_plans for i in gp['infos']}), 'losses': [l for gp in group_plans for l in gp['losses']],
            'exifTargets': sorted({(t['location'].split(':')[0], int(t['location'].split(':')[1], 16)) for gp in changed for t in gp['targets'] if t['family'] == 'exif' and t['changes']}),
            'iptcTargets': sorted({tuple(int(x) for x in t['location'].split(':')) for gp in changed for t in gp['targets'] if t['family'] == 'iptc'} | {(2, 60), (2, 63)} if iptc['changed'] else set()),
            'xmpTargets': sorted(xmp_props)}


def request_of(spec, at):
    return e3place.parse_entry(spec, None, at)


def plan_location_items(p, items, ctx):
    block = ctx.block
    ok = [i for i in items if i['status'] == 'ok']
    by_item = {e['item']: e for e in block['positions']}
    known = {i['id'] for i in items}
    for index, entry in enumerate(block['positions']):
        if entry['item'] not in known:
            fail('UNKNOWN_ITEM', 'the position names an item that is not in the media set', '$.positions[%d].item' % index, value=entry['item'][:64], items=sorted(known)[:20])
    for item in ok:
        decide(ctx, item, lambda item=item: location_item(ctx, item, by_item.get(item['id']), block))


def location_item(ctx, item, entry, block):
    at = item['file']
    spec = entry if entry is not None else block.get('default')
    if spec is None:
        return unchanged(item, 'noPosition')
    request = request_of(spec, '$.positions' if entry is not None else '$.default')
    plan = e3place.plan_item(request, item['payloads'], item['walk'], block['policies'], at)
    finish_location(item, plan, at)


def finish_location(item, plan, at, extra=None):
    problem = e3place.xmp_qualifier_problem(item['located'], plan['xmpTargets'])
    if problem:
        raise edits.Refusal('XMP_QUALIFIERS_WOULD_BE_LOST', 'an XMP value this write rewrites carries qualifiers that the rewrite would silently drop, so the item is refused rather than flattened', at, **problem)
    plan.update(outcome='located', iptc={'assignCharset': False, 'changed': False, 'digest': False, 'state': None, 'charset': None, 'created': False}, **(extra or {}))
    item['plan'] = plan
    item['args'] = plan['args']


def clock_spec(groups):
    """A reconcile specification that only groups: geotagging needs device groups for assumed offsets and shifts, not skew estimates."""
    return {'groups': groups, 'assumedOffsets': [], 'references': [], 'simultaneous': [], 'toleranceSeconds': '2', 'maxDriftRate': '0.001', 'maxDriftExtrapolationSeconds': 0, 'model': 'constant', 'assumeCorrect': []}


def plan_geotag_items(p, items, ctx):
    block = ctx.block
    ok = [i for i in items if i['status'] == 'ok']
    records_ = {i['id']: e3read.time_record(i['id'], i['e3fields']) for i in ok}
    try:
        report, exact = clockmodel.reconcile_exact(list(records_.values()), clock_spec(block['groups']), [i['id'] for i in items if i['status'] != 'ok'])
    except clockmodel.ClockProblem as error:
        e3reports.clock_problem(error)
    group_ids = {g['id'] for g in report['groups']}
    photo = block['photoTime']
    assumed = {}
    for index, entry in enumerate(photo['assumedOffsets']):
        if entry['group'] not in group_ids:
            fail('GROUP_MEMBERSHIP_INVALID', 'assumedOffsets names a group that does not exist in this media set', '$.photoTime.assumedOffsets[%d].group' % index, value=entry['group'][:64], groups=sorted(group_ids)[:20])
        assumed[entry['group']] = tc.parse_offset(entry['offset'])
    correction = photo['clockCorrection']
    shifts = {}
    if isinstance(correction, dict) and 'shifts' in correction:
        for index, entry in enumerate(correction['shifts']):
            if entry['group'] not in group_ids:
                fail('GROUP_MEMBERSHIP_INVALID', 'the clock correction names a group that does not exist in this media set', '$.photoTime.clockCorrection.shifts[%d].group' % index, value=entry['group'][:64], groups=sorted(group_ids)[:20])
            shifts[entry['group']] = tc.seconds_ns(entry['shift']['seconds'])
    ctx.exact = exact
    for item in ok:
        decide(ctx, item, lambda item=item: geotag_item(ctx, item, records_[item['id']], exact[item['id']], assumed, shifts))


def clock_plan_delta(ctx, item, record, assumed_offset=None):
    """``(delta_ns, planned)`` of a published ``correctTime`` plan for this item, with the stale, double-application, refused-entry and consistency refusals.

    The entry must be exactly what the correctTime planner produces from the plan's own recorded inputs and this capture (``recomputed_clock_entry``): every recorded
    component (local time, offset, fraction, targets, native assignments, delta) is compared in its own family's serialisation, so any edit that the planner would not
    have produced is ``PLAN_INCONSISTENT``. ``delta_ns`` is then the move of the item's *instant* between the verified before and after states of the captured group:
    the wall-clock move less any change of the recorded (or assumed) offset, so an offset set keeping the instant moves nothing and one keeping the wall clock moves it.

    ``planned`` is ``{'wall', 'offset'}`` when the plan sets an offset on an item that records none and has none assumed: the after state alone then establishes the
    instant (no before instant, offset or time zone is invented) and ``delta_ns`` is only the wall-clock move.
    """
    at = '$.photoTime.clockCorrection.plan'
    entry = next((e for e in ctx.clock_plan['items'] if e['id'] == item['id']), None)
    if entry is None:
        raise edits.Refusal('PLAN_STALE', 'the clock-correction plan does not list this item', at, item=item['id'])
    captured = next((g for g in entry.get('groups', []) if isinstance(g, dict) and g.get('group') == 'captured'), None)
    if isinstance(captured, dict) and isinstance(captured.get('before'), dict) and isinstance(captured.get('after'), dict) and captured['before'].get('local') != captured['after'].get('local') and record['wall'] is not None:
        current = tc.local_text(record['wall'] - record['wall'] % tc.NS, 0)
        if current == captured['after']['local'] and current != captured['before']['local']:
            raise edits.Refusal('CORRECTION_ALREADY_APPLIED', 'the captured time already equals what the clock-correction plan would produce; use clockCorrection none for a corrected file', at, item=item['id'])
    if entry['captureSha256'] != item['sha256']:
        raise edits.Refusal('PLAN_STALE', 'the capture is not the file the clock-correction plan was made for', at, item=item['id'], planned=entry['captureSha256'], captured=item['sha256'])
    reason = (entry.get('fault') or {}).get('code') if entry.get('status') == 'refused' else entry.get('reason') if entry.get('status') == 'unchanged' else None
    if entry.get('status') == 'refused' or (entry.get('status') == 'unchanged' and reason not in ('zeroNetChange', 'noCorrectionForGroup')):
        raise edits.Refusal('CLOCK_CORRECTION_UNAVAILABLE', 'the clock-correction plan has no correction for this item (%s), so its photo instant is not known' % reason, at, item=item['id'], planCode=str(reason)[:64])
    group = recomputed_clock_entry(ctx, item, entry, at)
    if group is None:
        return 0, None
    before, after = group['before'], group['after']
    wall_before, wall_after = plan_wall(before, at), plan_wall(after, at)
    off_before = None if before['offset'] is None else tc.parse_offset(before['offset'], at)
    off_after = None if after['offset'] is None else tc.parse_offset(after['offset'], at)
    recorded_offset = None if record['offset'] is None else tc.offset_text(record['offset'])
    if record['wall'] is None or wall_before != record['wall'] or before['offset'] != recorded_offset:
        raise edits.Refusal('PLAN_INCONSISTENT', 'the before state of the clock-correction plan is not what this capture records', at, item=item['id'])
    effective_before = off_before if off_before is not None else assumed_offset      # the offset the photo instant is built on today
    if effective_before is None:
        if off_after is not None:
            return wall_after - wall_before, {'wall': wall_after, 'offset': off_after}
        return wall_after - wall_before, None
    effective_after = off_after if off_after is not None else effective_before         # an offset the plan does not set stays as it is
    return (wall_after - wall_before) - (effective_after - effective_before) * 60 * tc.NS, None


def recomputed_clock_entry(ctx, item, entry, at):
    """The recomputed ``captured`` group plan of a clock-plan entry (``None`` when the entry has no such group), after the whole entry is shown to be the one the
    correctTime planner produces from the plan's recorded inputs and this capture; any difference is ``PLAN_INCONSISTENT``.

    The group, its declared correction (a shift, an offset to set or references), assumed offsets, fields and policies are those the clock plan records; the capture's
    time sources are read again from this run's own independent read. A ``from: references`` correction takes its wall-clock move from the plan (the whole media set that
    derived the skew is not available here); that move must agree with the recorded skew text, and everything else is still recomputed from it. The plan's authenticity is
    not established: a plan whose every component agrees is accepted as the correction it states.
    """
    from schemaxis.adaptors.exiftool import e3docs
    def inconsistent(message, **observed):
        return edits.Refusal('PLAN_INCONSISTENT', message, at, item=item['id'], **observed)
    try:
        declared = ctx.clock_plan['declared']
        block = {'timeFields': list(declared['timeFields']), 'policies': dict(declared['policies'])}
        corrections = {c['group']: c for c in declared['corrections']}
        assumed = {a['group']: tc.parse_offset(a['offset']) for a in declared['time']['assumedOffsets']}
        status = entry['status']
        group_id = entry['group'] if status == 'planned' else entry['detail']['group']
        if not isinstance(group_id, str) or not all(isinstance(g, str) for g in block['timeFields']):
            raise TypeError('group')
        correction = corrections.get(group_id)
        plan_basis = 'references' if correction is not None and correction.get('from') == 'references' else 'shift'
        skew_text, base = None, 0
        if correction is None:
            plan = unchanged_plan('noCorrectionForGroup', {'group': group_id})
        elif plan_basis == 'references' and status != 'planned':
            plan = unchanged_plan('zeroNetChange', {'group': group_id})        # no group records the wall-clock move: nothing to recompute it from
        else:
            if plan_basis == 'references':
                skew_text = entry['skewSeconds']
                first = entry['groups'][0]
                zero = e3time.plan_group(first['group'], item['e3fields'], item['payloads'], 0, set_offset_of(correction), assumed.get(group_id), block['policies'], item['file'])
                base = int(first['deltaNanoseconds']) - zero['deltaNanoseconds']
                if abs(base + tc.seconds_ns(skew_text.rstrip('~'))) > 1:
                    raise ValueError('skew')
            elif 'shift' in correction:
                base = tc.seconds_ns(correction['shift']['seconds'])
            plan = time_plan(block, item, group_id, correction, base, skew_text, plan_basis, assumed.get(group_id), item['file'])
    except edits.Refusal as error:
        raise inconsistent('the planner cannot reproduce the clock-correction plan entry from its recorded inputs and this capture (%s)' % error.code, planCode=error.code)
    except (KeyError, IndexError, TypeError, ValueError, AttributeError):
        raise inconsistent('the clock-correction plan records inputs or an entry that cannot be read')
    expected = json_safe(e3docs.entry_of(ctx.p, {'id': item['id'], 'sha256': item['sha256'], 'status': 'ok', 'plan': plan}))
    if expected != json_safe(entry):
        differing = sorted(k for k in set(expected) | set(entry) if expected.get(k) != entry.get(k))
        raise inconsistent('the clock-correction plan entry differs from the one its own recorded inputs and this capture produce', differs=differing[:8])
    return next((g for g in plan.get('groups', []) if g['group'] == 'captured'), None)


def plan_wall(state, at):
    """The local time of a plan state (``local`` second text and an optional digit ``fraction``) in nanoseconds."""
    wall, _ = tc.parse_local(state['local'], at)
    fraction = state.get('fraction')
    if fraction in (None, ''):
        return wall
    if not isinstance(fraction, str) or not fraction.isascii() or not fraction.isdigit() or len(fraction) > 9:
        raise ValueError('fraction')
    return wall + int(fraction.ljust(9, '0'))


def geotag_item(ctx, item, record, ex, assumed, shifts):
    block = ctx.block
    at = item['file']
    delta, planned = 0, None
    if ctx.clock_plan is not None:
        delta, planned = clock_plan_delta(ctx, item, record, assumed.get(ex['group']))
    elif ex['group'] in shifts:
        delta = shifts[ex['group']]
    try:
        instant, basis = e3track.photo_instant(record, assumed.get(ex['group']), -delta, planned)
    except edits.Refusal as error:
        return unresolved(ctx, item, error.code, error.message, **error.observed)
    elevation = block['track']['elevation']
    want = isinstance(elevation, dict)
    result = e3track.placement(ctx.index, instant, block, True)          # the logger's elevation is always looked at, so an undeclared reference can be reported
    if result['status'] != 'ok':
        return unresolved(ctx, item, result['code'], result['message'], **{k: v for k, v in result.items() if k not in ('status', 'code', 'message')}, instant=tc.local_text(instant) + 'Z')
    track = ctx.tracks[result['track']]
    spec = {'latitude': e3track.text9(result['latitude']), 'longitude': e3track.text9(result['longitude'])}
    if want and result.get('altitude') is not None:
        spec['altitude'] = {'meters': e3track.text3(result['altitude']), 'reference': elevation['reference']}
    if track['datum']:
        spec['datum'] = track['datum']
    if block['policies'].get('gpsStamp') == 'photoInstant':
        spec['gpsUtc'] = tc.local_text(instant) + 'Z'
    try:
        request = e3place.parse_entry(spec, None, '$.tracks')
    except Exception as error:
        code = getattr(getattr(error, 'fault', None), 'code', 'INVALID_ARGUMENT')
        raise edits.Refusal('ALTITUDE_OUT_OF_RANGE' if 'altitude' in str(error) else code, 'the interpolated value is outside the supported domain: ' + str(getattr(getattr(error, 'fault', None), 'message', error))[:160], at)
    plan = e3place.plan_item(request, item['payloads'], item['walk'], block['policies'], at, instant_ns=instant)
    evidence = e3track.public_placement(result)
    infos = list(plan['infos'])
    if not want and result.get('altitude') is not None:
        infos.append('elevationReferenceUndeclared')           # a GPX ele has no stated vertical reference: nothing is written unless the author declares one
    if want and result.get('altitude') is None:
        infos.append('altitudeUnavailable')
    if track['data']['counts']['geoidheightPresent']:
        infos.append('geoidheightPresent')                     # never applied: no geoid conversion is performed
    limit = block['policies'].get('maxSpeedMetersPerSecond')
    speed = result.get('evidence', {}).get('impliedSpeedMetersPerSecond')
    if limit is not None and speed is not None and Fraction(str(speed)) > Fraction(limit):
        infos.append('implausibleSpeed')
    plan['infos'] = sorted(set(infos))
    finish_location(item, plan, at, {'placement': evidence, 'photoInstant': {'utc': tc.local_text(instant) + 'Z', 'basis': basis, 'clockCorrectionNanoseconds': None if basis == 'plannedOffset' else delta}, 'track': track['id']})


def unresolved(ctx, item, code, message, **observed):
    """A geotag item that cannot be placed: a byte-identical copy with its reason (default), or a truthful outcome document (``refuseSlot``)."""
    unchanged(item, code, {'message': message, **{k: v for k, v in observed.items() if isinstance(v, (str, int, float)) or v is None}})


# ---------------------------------------------------------------- proofs, publications and reuse (called by the E2 writer)
KINDS = ('time', 'location', 'unchanged')
LOSSES = {
    'correctTime': [
        'Time is the recorded wall clock of each file; no time zone, daylight-saving rule or leap second is known. A reference true time, an assumed offset and an assumeCorrect group are declared by the author and published as declared: they are never verified, and a correct-looking result does not prove the camera clock was right.',
        'Every present source of a corrected field (EXIF, XMP, IPTC) is rewritten so the sources stay concordant; absent sources are not created, except offset carriers when the author sets an offset. GPS time stamps are independent evidence and are never shifted. A fraction keeps its digit count when that is exact and is extended when it must be; IPTC cannot hold a fraction, so it is truncated toward the earlier second and listed per item (iptcFractionDropped).',
        'The calendar is the proleptic Gregorian one over the years 1900 to 2100 with exact integer arithmetic; second 60 is refused wherever it appears. Maker-note times, preview Exif, XMP edit-history times, sidecar and file-system times are not interpreted and not changed.'],
    'setLocation': [
        'A position is written as an exact decimal under the fixed native protocol, with every reference letter explicit; the stored precision (a serialisation bound of 2e-10 degrees) is published as read back from the output and is not GPS accuracy. A zero never carries a south or west reference.',
        'An altitude is written only with the reference the author declares and only where the file\'s metadata edition can express it (Exif 3.x, or a file with no Exif and no GPS IFD); no vertical datum is converted and no ExifVersion is written. An XMP altitude cannot be expressed by the pinned ExifTool and is removed as a declared loss.',
        'GPS values that describe the old fix (altitude, datum, time stamps, error, speed, track and the like) are removed or kept as declared before the write; the camera direction is kept. Place names are not updated and nothing is geocoded.'],
    'geotagFromTrack': [
        'Positions are interpolated by Schemaxis (great-circle slerp between consecutive fixes, exact on a fix, no extrapolation) from captured GPX tracks parsed with a bounded, entity-free reader; the native geotag feature is never used. The path between fixes is unknown and no accuracy, confidence or error radius is claimed.',
        'The photo instant is the recorded capture time minus the recorded or declared UTC offset, moved by a declared clock correction applied to the photo instant only; there is no system time zone. An item that cannot be placed is published unchanged with its reason (or as an outcome document under refuseSlot).',
        'A coordinate or altitude is written as for setLocation; a GPX elevation is written only when the author declares what the logger recorded (seaLevel or ellipsoidal), and a geoid height is never applied.']}


def reusable_inputs(p):
    """Digests of the plan and track files an operation reads, so a changed track or plan invalidates reuse (a touched but unchanged file does not)."""
    import hashlib
    found = {}

    def add(path, limit, code, at):
        data = e3track.capture_bytes(path, limit, code, at)
        found[path] = hashlib.sha256(data).hexdigest()
        return data
    block = p['e3']
    if 'planFile' in block:
        data = add(block['planFile'], e3track.PLAN_BYTES, 'PLAN_UNREADABLE', '$.plan')
        try:
            inputs = json.loads(data.decode('utf-8')).get('inputs', {})
            for track in inputs.get('tracks', []):
                if isinstance(track, dict) and isinstance(track.get('path'), str):
                    add(track['path'], e3track.TRACK_BYTES, 'TRACK_UNREADABLE', '$.plan')
            clock = (inputs.get('photoTime') or {}).get('clockCorrection')
            if isinstance(clock, dict) and isinstance(clock.get('plan'), str):
                add(clock['plan'], e3track.PLAN_BYTES, 'PLAN_UNREADABLE', '$.plan')
        except (ValueError, UnicodeDecodeError, AttributeError, OSError, TypeError):
            pass
        return found
    for index, track in enumerate(block.get('tracks', [])):
        add(track['path'], e3track.TRACK_BYTES, 'TRACK_UNREADABLE', '$.tracks[%d].path' % index)
    correction = block.get('photoTime', {}).get('clockCorrection')
    if isinstance(correction, dict) and 'plan' in correction:
        add(correction['plan'], e3track.PLAN_BYTES, 'PLAN_UNREADABLE', '$.photoTime.clockCorrection.plan')
    return found


def readback(p, plan, item, payloads_out, at):
    """Proof R of an E3 item (time, location, or an unchanged copy) and the published after-values; returns the problem list."""
    from schemaxis.adaptors.exiftool import e3docs, e3proofs
    item['readback'] = None
    if plan['kind'] == 'time':
        item['readback'] = {'groups': [{'group': gp['group'], 'after': gp['after']} for gp in plan['groups']]}
        return e3proofs.time_readback(plan, item, payloads_out, at) + e3proofs.height_problems(plan, item['payloads'], payloads_out, at)
    if plan['kind'] == 'location':
        problems = e3proofs.location_readback(plan, payloads_out, at) + e3proofs.height_problems(plan, item['payloads'], payloads_out, at)
        item['readback'] = e3docs.published_readback(plan, payloads_out)
        return problems
    return e3proofs.height_problems(plan, item['payloads'], payloads_out, at)


def proof_r(plan):
    if plan['kind'] == 'time':
        return {'components': sorted('%s.%s.%s' % (f, fam, loc) for f, fam, loc in plan['expect']), 'groups': [gp['group'] for gp in plan['groups']]}
    if plan['kind'] == 'location':
        return {'exif': plan['exifActive'], 'xmp': plan['xmpActive'], 'bound': '2e-10 degrees (serialisation bound)', 'removed': plan['deletedExif']}
    return {'unchanged': True}


def after_anchors(p, item, payloads_out, record):
    """Anchors of the written file: the independent E3 field records of the output against the native listing of the output."""
    if item['plan']['kind'] == 'unchanged' or record is None:
        return 0, []
    reader = records.Record(payloads_out, VIEW)
    fields = {name: reader.field(name) for name in field_names(p)}
    return listing.anchors(item, fields, {'image': listing.index(record), 'sidecar': None})


# ---------------------------------------------------------------- exact verification codes for a tampered publication
def publication_difference(p, name, actual, expected):
    """``(code, message)`` for an E3 publication that differs from the one recomputed from the retained evidence: an edited plan is ``PLAN_INCONSISTENT`` and an
    edited interpolation is ``INTERPOLATION_MISMATCH``; ``None`` leaves the generic verification fault."""
    if name != PLAN_FILES[p['operation']]:
        return None
    try:
        found, wanted = json.loads(actual.decode('utf-8')), json.loads(expected.decode('utf-8'))
    except (ValueError, UnicodeDecodeError):
        return 'PLAN_INCONSISTENT', 'the plan document is not the document its own recorded inputs and captures produce'
    if p['operation'] == 'geotagFromTrack':
        if [i.get('placement') for i in found.get('items', []) if isinstance(i, dict)] != [i.get('placement') for i in wanted['items']]:
            return 'INTERPOLATION_MISMATCH', 'the interpolated placement the plan records differs from the one recomputed from the retained tracks and captures'
    return 'PLAN_INCONSISTENT', 'the plan document differs from the one its own recorded inputs and captures produce'


def slot_difference(recorded, expected):
    """``(code, message)`` when the recorded artifact slots differ from the recomputed ones in identity: a refused slot published as an image is ``FALSE_SUCCESS`` and an item
    that moved (or vanished) is ``SLOT_SHIFTED``; ``None`` when the identities agree (only digests differ)."""
    def identity(entry):
        return (entry.get('kind'), (entry.get('identity') or {}).get('item'))
    one, two = [identity(a) for a in recorded], [identity(a) for a in expected]
    for (rk, ri), (ek, ei) in zip(one, two):
        if rk == 'image' and ek != 'image' and ri == ei:
            return 'FALSE_SUCCESS', 'a slot the recomputed run refused is published as an image (item %s)' % ri
        if (rk, ri) != (ek, ei) and (ri != ei or rk != ek):
            return 'SLOT_SHIFTED', 'artifact slot positions differ from the manifest order: expected %s at this index, the receipt has %s' % (ei, ri)
    if len(one) != len(two):
        return 'SLOT_SHIFTED', 'the receipt holds %d artifact slots and the manifest order gives %d' % (len(one), len(two))
    return None
