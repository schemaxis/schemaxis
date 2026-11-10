"""E4 host operations over a bounded set of JPEG photos: ``exportSidecar``, ``planNames`` and ``organiseCopies``.

Every item is captured byte for byte, decoded by the independent readers into a typed snapshot of the internal ``fields/4`` view and anchored against one fixed
native listing, exactly like the E1 and E2 families. None of these operations rewrites an image:

* ``exportSidecar`` serializes one XMP sidecar per item from its typed snapshot (host serializer, closed property set). Proof S: the serializer re-run over the
  retained captures reproduces every sidecar byte for byte, the hardened reader re-reads exactly the planned typed values (no extra property), and a fresh fixed
  ExifTool listing of the produced sidecar carries exactly the expected XMP keys with agreeing values.
* ``planNames`` plans relative paths from typed capture facts with the closed token vocabulary, the declared sanitiser and collision rules, and publishes the plan.
* ``organiseCopies`` creates exact byte copies of the captures under ``organised/<relative path>`` (create-only, no links, one directory level at a time). Proof C:
  every copy hashes equal to its capture, paths equal the plan, the tree lists exactly the produced files and nothing else exists under ``organised/``.

Item faults never block the other items; a stable slot per item and kind keeps consumer indexes truthful. Verification recomputes every proof from the retained bytes.
"""
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import tempfile

from schemaxis.adaptors.exiftool import adaptor as legacy, catalogue, e4model, editing, listing, mediaset, naming, options, records, workbench as wb, xmp as xmp_reader, xmpwrite
from schemaxis.artifacts import atomic_json
from schemaxis.core.declarations import validate_arguments
from schemaxis.core.faults import SchemaxisError
from schemaxis.dispatch import cancellation_requested, execution_deadline, remaining_timeout
from schemaxis.errors import fail

OPERATIONS = tuple(options.E4_HOST_OPTIONS)
VERSION = legacy.VERSION
PLAN_VERSION = 'schemaxis.exiftool.e4.plan/1'
REPORT_VERSION = 'schemaxis.exiftool.e4.report/1'
RUNTIME, PERL = legacy.RUNTIME, legacy.PERL
CAPTURED, STAGE, SIDECARS, OUTCOMES, REJECTED, ORGANISED, INPUTS = 'captured', 'stage', 'sidecars', 'outcomes', 'rejected', 'organised', 'inputs'
JSON_LIMIT = wb.JSON_LIMIT
NAME_FIELDS = ('capturedLocalE3', 'capturedOffsetE3', 'capturedSubSecondE3', 'cameraMake', 'cameraModel')
PLAN_FILE_LIMIT = 16 * 1024 * 1024
METADATA = '.metadata.json'
EXPORT_DEFAULTS = {'ambiguous': 'refuseItem', 'altitude': 'omitUnlessReferenceKnown', 'existingSidecar': 'ignore'}
LOSSES = {
    'exportSidecar': [
        'Selected, present, typed facts only: the sidecar holds the fields the author chose in a closed set of 29 XMP properties. MakerNotes, unknown tags, structures (location created, contact, regions, history), thumbnails and every other value are neither read into the sidecar nor claimed absent. An existing adjacent sidecar is never merged or modified.',
        'A field is written only when every source that records it agrees; ambiguous values are refused or skipped as declared, and an unreadable value is never treated as absent. Text is exact: nothing is normalised, trimmed or case-folded, and a character XML 1.0 cannot carry refuses the item instead of being stripped.',
        'Altitude is written as exif:GPSAltitude with the Exif 3.x reference in exifEX:GPSAltitudeRef only where the typed height reference is ellipsoidal or sea level with a known sign; an unspecified legacy reference omits the altitude and says so. ExifTool 13.55 lists that reference literally, but its Composite altitude reads it with legacy 0/1 meanings and inverts the sign for code 2, so every sidecar with code 2 carries that residual.',
        'Coordinates use the XMP GPSCoordinate form: whole degrees, minutes and seconds only when the stored values are whole, otherwise decimal minutes rounded half-even to 8 fractional digits; the plan states the stored value, the written value and the difference in arc seconds. A GPS time stamp is written only when both stored date and time exist.',
        'ExifTool 13.55 lists each produced sidecar once to anchor the properties; native agreement shows the literal is present and parseable. It is not independent truth about meaning, and the sidecar is not a proof of authenticity or provenance.'],
    'planNames': [
        'Names come from recorded capture facts only: the camera-recorded wall time and offset, camera make and model, the original file name and the item id. No file modification time, system time zone or locale is used, and no capture time is certified.',
        'The vocabulary is closed: no template language, expression, date arithmetic or regular expression. Every character replacement, truncation, normalisation, fallback and collision suffix is declared per item; two outputs whose names are equal after case folding and Unicode normalisation collide.',
        'The plan names files; it does not copy them. A plan made for one set of captured bytes is stale for any other, and the sanitiser targets portable names, not the rules of a particular destination file system.'],
    'organiseCopies': [
        'Exact byte copies of the captures: every output is the capture byte for byte (SHA-256 equal); only its name and folder differ. Metadata is never read from a copy or rewritten, and the original files are never modified or moved.',
        'Copies are created only inside this run under organised/, create-only and without following links; there is no delivery outside the run and no archive. A surprise on disk (an existing target, a link in the path) refuses that item and the others continue.',
        'An adjacent sidecar is copied beside its image under the same stem when the plan carries sidecars; an unrelated sidecar is never matched by name alone. Organising is not privacy or provenance certification.']}


# ---------------------------------------------------------------- planning
def narrow_media(media):
    planned = mediaset.plan_media(media)
    if planned['kind'] == 'items':
        for index, item in enumerate(planned['items']):
            if Path(item['path']).suffix.lower() not in mediaset.RASTER_SUFFIXES:
                fail('INVALID_PHOTO_SOURCE', 'select an image file (.jpg, .jpeg, .tif, .tiff, .dng, .png, .webp, .heic, .heif or .avif): sidecar-only items are not subjects of this operation', '$.media.items[%d].path' % index)
        return planned
    folder = planned['folder']
    folder['extensions'] = [e for e in folder['extensions'] if e in mediaset.RASTER_SUFFIXES] or list(mediaset.IMAGE_SUFFIXES)
    return planned


def rule_of(p, at='$.names'):
    try:
        return naming.normalise_rule({k: p[k] for k in options.NAME_RULE if k in p})
    except naming.NamingError as error:
        fail(error.code, error.message, error.location.replace('$.names', at), **error.observed)


def plan(document):
    op = document.get('operation')
    declared = options.E4_HOST_OPTIONS[op]
    extra = sorted(set(document) - {'version', 'operation'} - set(declared))
    if extra:
        fail('UNKNOWN_ARGUMENT', 'unsupported keys for ' + op, '$', keys=extra)
    if document.get('version') != VERSION:
        fail('UNSUPPORTED_VERSION', 'expected ' + VERSION, '$.version')
    p = validate_arguments(declared, {k: v for k, v in document.items() if k in declared})
    out = {'version': PLAN_VERSION, 'operation': op, 'media': narrow_media(p['media'])}
    if op == 'exportSidecar':
        try:
            selected = e4model.selection(p['transfer'])
        except e4model.SelectionError as error:
            fail('INVALID_TRANSFER_SELECTION', error.message, error.location, **error.observed)
        out.update(transfer={'groups': [g for g in e4model.GROUPS if g in p['transfer'].get('groups', [])], 'fields': selected}, policies={**EXPORT_DEFAULTS, **p.get('policies', {})}, fields=e4model.view_names(selected))
    elif op == 'planNames':
        out.update(names={'rule': rule_of(p)}, fields=list(NAME_FIELDS))
    else:
        names = p['names']
        if isinstance(names, str):
            if '\0' in names or not names.startswith('/'):
                fail('PLAN_UNREADABLE', 'select an absolute plan file path', '$.names')
            out['names'] = {'planFile': names}
        else:
            out['names'] = {'rule': rule_of(names)}
        out.update(sidecars=p.get('sidecars', 'carry'), fields=list(NAME_FIELDS))
    out.update(settings={'nativeArguments': listing.FIXED, 'threads': 1, 'userConfiguration': False, 'nativeWrite': False},
               budget={'maxItems': mediaset.MAX_ITEMS, 'maxItemBytes': mediaset.ITEM_BYTES, **mediaset.large_bounds(out['media']), 'maxTotalBytes': mediaset.TOTAL_BYTES, 'maxSidecarBytes': xmpwrite.MAX_BYTES},
               catalogue={'version': catalogue.VERSION_E4, 'sha256': catalogue.digest(catalogue.VERSION_E4)}, losses=LOSSES[op])
    return out


def plan_hash(p): return legacy.plan_hash(p)


def resources(document, execution, identity):
    if execution.get('threads', 1) != 1:
        fail('INVALID_EXECUTION', 'metadata work runs one serial native thread', identity)
    return {'threads': 1}


def reusableInputs(document):
    return reusable(plan(document))


def reusable(p):
    found = {}
    for target in wb.collect(p)[1]:
        for entry in [target, target.get('sidecar')]:
            if entry is not None:
                found[entry['path']] = hashlib.sha256(mediaset.read_file(entry['path'], entry.get('identity'), mediaset.item_limit(entry['path']), '$.media')).hexdigest()
    if p['media']['kind'] == 'folder':
        rows, _, _ = mediaset.expand(p['media'])
        found[p['media']['folder']['path']] = mediaset.manifest_digest(rows)
    plan_file = p.get('names', {}).get('planFile')
    if plan_file:
        found[plan_file] = hashlib.sha256(legacy.bounded(plan_file, 'PLAN_UNREADABLE', PLAN_FILE_LIMIT, follow=True)).hexdigest()
    return found


def schema():
    from schemaxis.schema import DRAFT, argument_schema, object_schema

    def branch(op, required):
        return object_schema({'version': {'const': VERSION}, 'operation': {'const': op}, **{k: argument_schema(v) for k, v in options.E4_HOST_OPTIONS[op].items()}}, ['version', 'operation', *required])
    branches = [branch('exportSidecar', ['media', 'transfer']), branch('planNames', ['media', 'name']), branch('organiseCopies', ['media', 'names'])]
    declared = {}
    for o in options.E4_HOST_OPTIONS.values():
        for k, v in o.items():
            variants = declared.setdefault(k, [])
            if v not in variants:
                variants.append(v)
    properties = {'operation': {'enum': list(OPERATIONS)}, **{k: argument_schema(v[0] if len(v) == 1 else {'type': 'union', 'options': [{a: b for a, b in x.items() if a != 'required'} for x in v]}) for k, v in declared.items()}}
    return {'properties': properties, 'oneOf': branches}


# ---------------------------------------------------------------- evidence helpers
def encode(value): return legacy.encode_json(value)
def read_json(directory, name): return wb.read_json(directory, name)
def digest_of(directory, name, limit=JSON_LIMIT): return legacy.sha(legacy.bounded(directory / name, limit=limit))
def limit_of(name): return mediaset.item_limit(name) if name.startswith((CAPTURED + '/', REJECTED + '/', STAGE + '/', ORGANISED + '/', SIDECARS + '/')) else 72 * 1024 * 1024 if name.startswith(INPUTS + '/') else JSON_LIMIT
def stage_file(item_id): return '%s/%s.xmp' % (STAGE, item_id)
def static_stages(after): return ('version', 'libraries', 'modules', 'before') + (('after',) if after else ())


def evidence_names(p, captured, after):
    names = {'authored.json', 'plan.json', 'captures.json', 'runtime.json'}
    for entry in captured['items']:
        if entry['fault'] is None:
            names.add(entry['file'])
            if entry['sidecar']:
                names.add(entry['sidecar']['file'])
    for stage in static_stages(after):
        names |= {stage + x for x in ('-launcher.py', '-inputs.json', '-submission.json', '.stdout', '.stderr')}
    if 'plan' in captured.get('inputs', {}):
        names.add(captured['inputs']['plan']['file'])
    if p['operation'] == 'organiseCopies':
        names.add('organise-runtime.json')
    return names


def native_names(items):
    return wb.native_names(items)


def stage_path_of(directory, name):
    item_id = Path(name).stem
    for sub in (SIDECARS, REJECTED):
        if (directory / sub / (item_id + '.xmp')).is_file():
            return '%s/%s.xmp' % (sub, item_id)
    return name


# ---------------------------------------------------------------- admission (shared by run and verify)
def admit(directory, p, captured):
    items = []
    use_sidecar = p['operation'] != 'exportSidecar'
    for entry in captured['items']:
        item = {**entry, 'status': 'fault' if entry['fault'] else 'ok', 'fields': None, 'native': None, 'notes': [], 'frame': None, 'payloads': None, 'located': None, 'bytes_': None}
        items.append(item)
        if entry['fault'] is not None:
            continue
        data = legacy.bounded(directory / entry['file'], limit=mediaset.item_limit(entry['file']))
        if legacy.sha(data) != entry['sha256'] or len(data) != entry['bytes']:
            fail('VERIFICATION_FAILED', 'a retained captured item differs from its capture record', entry['file'])
        side = None
        if entry['sidecar']:
            side_data = legacy.bounded(directory / entry['sidecar']['file'], limit=mediaset.ITEM_BYTES)
            if legacy.sha(side_data) != entry['sidecar']['sha256'] or len(side_data) != entry['sidecar']['bytes']:
                fail('VERIFICATION_FAILED', 'a retained captured sidecar differs from its capture record', entry['sidecar']['file'])
            side = wb.locate(side_data, entry['sidecar']['file']) if use_sidecar else None
        located = wb.locate(data, entry['file'])
        if located['container'] != entry['container']:
            fail('VERIFICATION_FAILED', 'the retained item container differs from its capture record', entry['file'])
        _, fields, payloads = records.build(located, p['fields'], side, p['catalogue']['version'])
        item.update(fields=fields, notes=payloads.notes, frame=located['frame'], payloads=payloads, located=located, bytes_=data)
    return items


def refuse(item, code, message, location=None, **observed):
    item.update(status='refused', fault=wb.fault_dict(code, message, location or item['file'], **observed))


# ---------------------------------------------------------------- exportSidecar
def snapshot_of(item, p):
    return e4model.snapshot(item['payloads'], p['transfer']['fields'])


def plan_export(p, items):
    selected, policies = p['transfer']['fields'], p['policies']
    for item in items:
        if item['status'] != 'ok':
            continue
        if policies['existingSidecar'] == 'refuse' and item['sidecar']:
            refuse(item, 'SIDECAR_EXISTS', 'an adjacent sidecar exists and the policy refuses to produce a second one', item['sidecar']['relative'])
            continue
        snap = snapshot_of(item, p)
        model, losses, infos, faults, skipped = e4model.sidecar_model(snap, selected, policies)
        if faults:
            first = faults[0]
            refuse(item, first['code'], first['message'], item['file'], faults=faults[:8], **{k: v for k, v in first.items() if k in ('field',)})
            continue
        if not model:
            refuse(item, 'SIDECAR_NOTHING_TO_WRITE', 'every selected field is absent or skipped, so there is nothing to write into a sidecar', item['file'], skipped=skipped[:8])
            continue
        try:
            data = xmpwrite.build(model)
        except xmpwrite.SidecarError as error:
            refuse(item, error.code, error.message, item['file'], **error.observed)
            continue
        item['export'] = {'model': model, 'losses': losses, 'infos': infos, 'skipped': skipped, 'bytes': data, 'quantisation': e4model.quantisation(model), 'sha256': legacy.sha(data),
                          'keys': sorted(xmpwrite.keys_of(model)), 'snapshot': {f: {k: v for k, v in r.items() if k in ('state', 'reconciliation')} for f, r in snap.items()}}


def native_date(local, sub, offset):
    return local[:10].replace('-', ':') + ' ' + local[11:] + ('.' + sub if sub else '') + (offset or '')


def native_expectation(model):
    """``{lowercase native key: (kind, expected)}`` for every produced property (AM7 key map; AM11 15-significant-digit rationals)."""
    out = {}
    for key, prop, form, native in xmpwrite.ROWS:
        if key not in model:
            continue
        value, name = model[key], 'XMP:' + native
        if form == 'alt':
            out[name.lower()] = ('text', value['text'])
            for entry in value.get('languages', []):
                out[(name + '-' + entry['language']).lower()] = ('text', entry['text'])
        elif form in ('bag', 'seq'):
            out[name.lower()] = ('list', list(value))
        elif form == 'text':
            out[name.lower()] = ('text', value)
        elif form == 'integer':
            out[name.lower()] = ('text', str(value))
        elif form == 'rational':
            out[name.lower()] = ('ratio', tuple(value))
        elif form == 'date':
            out[name.lower()] = ('text', native_date(value['local'], value.get('sub'), value.get('offset')))
        elif form == 'coordinate':
            from fractions import Fraction
            (dn, dd), (mn, md), (sn, sd) = value['components']
            total = Fraction(dn, dd) + Fraction(mn, md) / 60 + Fraction(sn, sd) / 3600
            out[name.lower()] = ('degrees', -total if value['ref'] in ('S', 'W') else total)
        elif form == 'gpsTime':
            out[name.lower()] = ('text', value[:10].replace('-', ':') + ' ' + value[11:])
    return out


def native_problems(model, record):
    """Mismatches between the produced properties and the fresh fixed listing of the sidecar: the XMP key set must be exactly the expected one."""
    from fractions import Fraction
    from schemaxis.adaptors.exiftool import codecs
    problems = []
    if record is None or record['fault'] or record['errors'] or record['warnings']:
        return [{'message': 'the native listing of the produced sidecar is missing, faulted or carries a warning or error'}]
    found = {}
    if any(o['group0'] == 'Composite' for o in record['observations']):
        return [{'message': 'the listing carries a Composite key, so it ran without -e: the native Composite altitude would misread the exifEX altitude reference'}]
    for o in record['observations']:
        if o['group0'] == 'XMP':
            found['XMP:%s:%s' % (o['group1'], o['name'])] = o['value']
    lowered = {k.lower(): v for k, v in found.items()}
    expected = native_expectation(model)
    if len(lowered) != len(found):
        problems.append({'message': 'two native keys differ only by case'})
    if set(lowered) != set(expected):
        problems.append({'message': 'the native XMP key set differs from the expected property set', 'missing': sorted(set(expected) - set(lowered))[:8], 'unexpected': sorted(set(lowered) - set(expected))[:8]})
        return problems
    for key, (kind, wanted) in expected.items():
        token = lowered[key]
        if kind == 'text':
            ok = str(token) == wanted
        elif kind == 'list':
            ok = ([str(t) for t in token] if isinstance(token, list) else [str(token)]) == wanted
        elif kind == 'ratio':
            ok = not isinstance(token, list) and str(token) == codecs.native_float_text(wanted)
        else:
            native = codecs.native_exact(token) if not isinstance(token, list) else None
            ok = native is not None and abs(native - wanted) <= Fraction(1, 10 ** 9)
        if not ok:
            problems.append({'key': key, 'message': 'native reports %s, the model expects %s' % (str(token)[:60], str(wanted)[:60])})
    return problems


def check_sidecar_bytes(item, data, at):
    """S(1) and S(2): the retained bytes are the serializer's output, and the hardened reader re-reads exactly the planned typed values."""
    export = item['export']
    if data != export['bytes']:
        fail('SIDECAR_NOT_REPRODUCIBLE', 'the serializer over the retained captures does not reproduce the sidecar byte for byte', at, item=item['id'])
    try:
        found = xmp_reader.parse(data)
    except xmp_reader.Problem as error:
        fail('SIDECAR_NOT_REPRODUCIBLE', 'the hardened reader does not accept the sidecar: ' + error.message, at, item=item['id'], cause=error.code)
    if found != xmpwrite.expected(export['model']):
        fail('SIDECAR_NOT_REPRODUCIBLE', 'the hardened reader re-reads values other than the planned typed values (or an extra property)', at, item=item['id'])


# ---------------------------------------------------------------- planNames
def subject_of(item, p):
    """The typed naming subject of one admitted item: independent time sources by family, camera text, original name parts."""
    fields = item['fields']
    return {'id': item['id'], 'order': item['order'], 'stem': Path(item['relative']).stem, 'suffix': Path(item['relative']).suffix, 'container': item['container'], 'brand': (item.get('located') or {}).get('brand'), 'sidecar': bool(item['sidecar']),
            'time': time_sources(fields), 'cameraMake': text_field(fields['cameraMake']), 'cameraModel': text_field(fields['cameraModel'])}


def text_field(record):
    return {'state': record['state'], 'value': record['canonical'] if record['state'] == 'present' else None}


def family_state(sources, family):
    rows = [s for s in sources if s['family'] in ((family, 'xmp-sidecar') if family == 'xmp' else (family,))]
    states = {s['state'] for s in rows if s['state'] != 'notApplicable'}
    return rows, states


def time_sources(fields):
    local, offset, sub = fields['capturedLocalE3'], fields['capturedOffsetE3'], fields['capturedSubSecondE3']

    def aggregate(record, state_only=False):
        return record['state']
    out = {}
    agg_state = e4model.combine({local['state']}) if local['state'] != 'ambiguous' else 'ambiguous'
    out['aggregate'] = {'state': local['state'], 'local': local['canonical'] if local['state'] == 'present' else None, 'offset': offset['canonical'] if offset['state'] == 'present' else None,
                        'offsetState': offset['state'], 'sub': sub['canonical'] if sub['state'] == 'present' else None, 'subState': sub['state'],
                        'values': [{'family': s['family'], 'value': s['canonical']} for s in local['sources'] if s['state'] == 'present']}
    if offset['state'] in ('ambiguous', 'unreadable', 'unsupported') and local['state'] == 'present':
        out['aggregate'].update(state=offset['state'] if offset['state'] != 'ambiguous' else 'ambiguous')
    orphans = e4model.unanchored(local, offset, sub)        # an offset or fraction only a carrier without its own local time states is never merged into the time other carriers state
    if orphans:
        out['aggregate']['unanchored'] = orphans
    for family in ('exif', 'xmp', 'iptc'):
        rows, states = family_state(local['sources'], family)
        present = [s for s in rows if s['state'] == 'present']
        state = 'present' if present and len({s['canonical'] for s in present}) == 1 and states <= {'present', 'absent'} else 'ambiguous' if len({s['canonical'] for s in present}) > 1 else e4model.combine(states) if states else 'absent'
        orows, _ = family_state(offset['sources'], family)
        opresent = [s['canonical'] for s in orows if s['state'] == 'present']
        srows, _ = family_state(sub['sources'], family)
        spresent = [s['canonical'] for s in srows if s['state'] == 'present']
        sstates = {s['state'] for s in srows}
        out[family] = {'state': state, 'local': present[0]['canonical'] if present and state == 'present' else None, 'offset': opresent[0] if opresent else None,
                       'sub': spresent[0] if spresent else None, 'subState': 'present' if spresent else 'unreadable' if sstates & {'unreadable', 'ambiguous'} else 'absent'}
    return out


def plan_names(p, items, rule):
    subjects = [subject_of(i, p) for i in items if i['status'] == 'ok']
    try:
        plan_ = naming.plan(rule, subjects)
    except naming.NamingError as error:
        fail(error.code, error.message, error.location, **error.observed)
    by_id = {r['id']: r for r in plan_['items']}
    for item in items:
        if item['status'] != 'ok':
            continue
        row = by_id[item['id']]
        row['captureSha256'] = item['sha256']
        row['source'] = {'path': item['relative'], 'bytes': item['bytes'], 'sha256': item['sha256'], 'container': item['container']}
        if row['status'] == 'refused':
            item.update(status='refused', fault=wb.fault_dict(row['fault']['code'], row['fault']['message'], item['file'], **{k: v for k, v in row['fault'].items() if k not in ('code', 'message', 'location')}))
    return plan_


def names_document(p, items, plan_, ctx):
    """The published name-plan document: the rule, every item's plan row or refusal, the capture pins and the catalogue digest."""
    rows = []
    for item in items:
        row = next((r for r in plan_['items'] if r['id'] == item['id']), None)
        if row is None:
            rows.append({'id': item['id'], 'order': item['order'], 'status': 'refused', 'fault': item['fault'], 'captureSha256': None, 'relativePath': None, 'sidecarPath': None, 'notes': []})
        else:
            rows.append(row)
    return {'version': naming.VERSION, 'operation': 'planNames', 'runtime': RUNTIME, 'catalogue': p['catalogue'], 'rule': plan_['rule'], 'ruleSha256': plan_['ruleSha256'], 'items': rows,
            'counts': {'items': len(rows), 'planned': sum(1 for r in rows if r['status'] == 'planned'), 'refused': sum(1 for r in rows if r['status'] == 'refused')},
            'statement': 'A deterministic name plan from recorded capture facts. It names files, it does not copy them, and it is valid only for the captured bytes it lists.'}


def names_csv(plan_doc):
    columns = [('id', 'text', False), ('status', 'text', False), ('relativePath', 'text', True), ('sidecarPath', 'text', True), ('code', 'text', True)]
    table = [[r['id'], r['status'], r.get('relativePath'), r.get('sidecarPath'), (r.get('fault') or {}).get('code')] for r in plan_doc['items']]
    return wb.csv_bytes(columns, table)


# ---------------------------------------------------------------- the plan file of organiseCopies (a published planNames document)
def load_plan_file(data, at):
    try:
        doc = legacy.strict_json(data, at, 'PLAN_INVALID')
    except SchemaxisError as error:
        fail('PLAN_INVALID', 'the name plan is not strict JSON: ' + error.fault.message, at)
    if not isinstance(doc, dict) or doc.get('version') != naming.VERSION or doc.get('operation') != 'planNames' or not isinstance(doc.get('items'), list) or not isinstance(doc.get('rule'), dict):
        fail('PLAN_INVALID', 'the file is not a planNames document of this version', at)
    return doc


def check_plan_fresh(doc, rule, items, p):
    """A name plan applies only to the bytes, catalogue and rule it was made for (``NAME_PLAN_STALE``): the whole run is refused before anything is copied."""
    recorded = [(r['id'], r.get('captureSha256')) for r in doc['items']]
    current = [(i['id'], i['sha256']) for i in items]
    if doc.get('catalogue') != p['catalogue']:
        fail('NAME_PLAN_STALE', 'the plan was made with another catalogue version or digest', '$.names', recorded=doc.get('catalogue'), current=p['catalogue'])
    if recorded != current:
        changed = sorted({a for a, b in recorded if (a, b) not in current} | {a for a, b in current if (a, b) not in recorded})
        fail('NAME_PLAN_STALE', 'the plan lists other capture bytes or another set of folder members than this run captured, so it could name different bytes', '$.names', items=changed[:20])
    if doc['rule'] != rule:
        fail('NAME_PLAN_STALE', 'the plan rule is not the normalised rule its own digest describes', '$.names')
    if doc.get('ruleSha256') != hashlib.sha256(json.dumps(rule, sort_keys=True).encode()).hexdigest():
        fail('NAME_PLAN_STALE', 'the plan rule digest differs from its rule', '$.names')


# ---------------------------------------------------------------- run context (rebuilt identically at run time and in verification)
class Context:
    def __init__(self, p, directory, captured):
        self.p, self.directory = p, directory
        self.plan_doc = None
        inputs = captured.get('inputs', {})
        if 'plan' in inputs:
            data = (directory / inputs['plan']['file']).read_bytes()
            if legacy.sha(data) != inputs['plan']['sha256'] or len(data) != inputs['plan']['bytes']:
                fail('CAPTURE_CHANGED', 'a retained captured input differs from its capture record', inputs['plan']['file'])
            self.plan_doc = load_plan_file(data, '$.names')
        self.rule = self.plan_doc['rule'] if self.plan_doc else p.get('names', {}).get('rule')


def capture_plan(p, directory):
    block = p.get('names', {})
    if 'planFile' not in block:
        return {}
    (directory / INPUTS).mkdir(exist_ok=True)
    data = legacy.bounded(block['planFile'], 'PLAN_UNREADABLE', PLAN_FILE_LIMIT, follow=True, location='$.names')
    (directory / INPUTS / 'names-plan.json').write_bytes(data)
    return {'plan': {'source': block['planFile'], 'file': INPUTS + '/names-plan.json', 'sha256': legacy.sha(data), 'bytes': len(data)}}


# ---------------------------------------------------------------- outcome documents
def outcome_document(item, op, kind='outcome'):
    return {'version': REPORT_VERSION, 'operation': op, 'item': item['id'], 'kind': kind, 'status': item['status'], 'fault': item.get('fault'),
            'statement': 'This is the truthful outcome of one slot of the set, kept at its stable position. It is not a published image or sidecar.'}


def no_sidecar_document(item, op, reason):
    return {'version': REPORT_VERSION, 'operation': op, 'item': item['id'], 'kind': 'noSidecar', 'reason': reason,
            'statement': 'There is no sidecar at this slot: the item has none, it was omitted by the plan, or the item was not written.'}


# ---------------------------------------------------------------- per-operation planning of the admitted items (shared by run and verify)
def prepare(p, items, ctx):
    """Per-operation decisions over the admitted items; item refusals are recorded on the items. Returns the operation's plan object (or ``None``)."""
    op = p['operation']
    if op == 'exportSidecar':
        plan_export(p, items)
        return None
    rule = ctx.rule
    plan_ = plan_names(p, items, rule)
    if op == 'organiseCopies' and ctx.plan_doc is not None:
        check_plan_fresh(ctx.plan_doc, rule, items, p)
    return plan_


def plan_row(plan_, item_id):
    return next((r for r in plan_['items'] if r['id'] == item_id), None)


def intended_copies(p, items, plan_):
    """The exact copies the plan calls for: ``[(item, relative path, bytes, kind)]`` in slot order (images first, then sidecars)."""
    images, sidecars = [], []
    for item in items:
        row = plan_row(plan_, item['id'])
        if item['status'] != 'ok' or row is None or row['status'] != 'planned':
            continue
        images.append((item, row['relativePath'], item['bytes_'], 'image'))
        if p['sidecars'] == 'carry' and item['sidecar']:
            sidecars.append((item, row['sidecarPath'], legacy.bounded(item['sidecar_path'], limit=mediaset.ITEM_BYTES), 'sidecar'))
    return images, sidecars


def build(p, rows, items, plan_, natives, ctx, after, runtime, directory):
    """``(files, copies, table, extras)``: every derived publication bytes by name, the exact copies, the per-item rows and the report inputs; recomputed identically by verification."""
    op = p['operation']
    files, copies, table = {}, [], []
    failures = {f['item']: f for f in (runtime or {}).get('failures', [])}
    manifest_status = {}
    if op == 'exportSidecar':
        results = {}
        for item in items:
            if item['status'] != 'ok':
                results[item['id']] = ('refused', item['fault'], [])
                continue
            problems = native_problems(item['export']['model'], after.get(stage_file(item['id']))) if after is not None else []
            if problems:
                results[item['id']] = ('failed', wb.fault_dict('SIDECAR_ANCHOR_MISMATCH', 'ExifTool and the produced sidecar disagree, so the sidecar is not published', item['file'], problems=problems[:8]), problems)
            else:
                results[item['id']] = ('written', None, [])
        for index, item in enumerate(items):
            status, fault, problems = results[item['id']]
            row = {'id': item['id'], 'order': item['order'], 'status': status, 'artifactIndex': index, 'source': {'path': item['relative'], 'bytes': item['bytes'], 'sha256': item['sha256'], 'container': item['container']}}
            if status == 'written':
                x = item['export']
                row['sidecar'] = {'file': '%s/%s.xmp' % (SIDECARS, item['id']), 'bytes': len(x['bytes']), 'sha256': x['sha256']}
                row['properties'] = [{'property': prop, 'nativeKey': 'XMP:' + native} for key, prop, _, native in xmpwrite.ROWS if key in x['model']]
                row['skipped'], row['losses'], row['infos'], row['quantisation'], row['snapshotStates'] = x['skipped'], x['losses'], x['infos'], x['quantisation'], x['snapshot']
                row['proofs'] = {'S': {'reproduced': True, 'reread': True, 'nativeAnchored': True, 'nativeKeys': x['keys']}}
                files[row['sidecar']['file']] = x['bytes']
            else:
                row['fault'] = fault
                files['%s/%s.json' % (OUTCOMES, item['id'])] = encode(outcome_document({**item, 'status': status, 'fault': fault}, op))
            table.append(row)
    elif op == 'planNames':
        doc = names_document(p, items, plan_, ctx)
        files['names-plan.json'] = encode(doc)
        files['names.csv'] = names_csv(doc)
        for index, item in enumerate(items):
            row_plan = plan_row(plan_, item['id'])
            status = 'planned' if item['status'] == 'ok' else 'refused'
            row = {'id': item['id'], 'order': item['order'], 'status': status, 'artifactIndex': None, 'source': {'path': item['relative'], 'bytes': item['bytes'], 'sha256': item['sha256'], 'container': item['container']}}
            if status == 'refused':
                row['fault'] = item['fault']
            else:
                row.update(relativePath=row_plan['relativePath'], sidecarPath=row_plan['sidecarPath'])
            table.append(row)
    else:
        doc = names_document(p, items, plan_, ctx)
        files['names-plan.json'] = encode(doc)
        images, sidecars = intended_copies(p, items, plan_)
        sidecar_of = {i['id']: (path, data) for i, path, data, _ in sidecars}
        image_of = {i['id']: (path, data) for i, path, data, _ in images}
        n = len(items)
        for index, item in enumerate(items):
            fault = failures.get(item['id'])
            written = item['id'] in image_of and fault is None
            status = 'written' if written else 'failed' if item['id'] in image_of else 'refused'
            row = {'id': item['id'], 'order': item['order'], 'status': status, 'artifactIndex': index, 'source': {'path': item['relative'], 'bytes': item['bytes'], 'sha256': item['sha256'], 'container': item['container']}}
            if written:
                path, data = image_of[item['id']]
                row['output'] = {'file': '%s/%s' % (ORGANISED, path), 'relativePath': path, 'bytes': len(data), 'sha256': legacy.sha(data)}
                copies.append((path, data, item['id'], 'image'))
                if item['id'] in sidecar_of:
                    spath, sdata = sidecar_of[item['id']]
                    row['sidecar'] = {'file': '%s/%s' % (ORGANISED, spath), 'relativePath': spath, 'bytes': len(sdata), 'sha256': legacy.sha(sdata)}
                    copies.append((spath, sdata, item['id'], 'sidecar'))
            else:
                if status == 'failed':
                    row['fault'] = wb.fault_dict(fault['code'], fault['message'], item['file'], **{k: v for k, v in fault.items() if k not in ('item', 'code', 'message')})
                else:
                    row['fault'] = item['fault']
                files['%s/%s.json' % (OUTCOMES, item['id'])] = encode(outcome_document({**item, 'status': status, 'fault': row['fault']}, op))
            table.append(row)
        for index, item in enumerate(items):
            row = table[index]
            if row['status'] != 'written' or 'sidecar' not in row:
                reason = 'omitted' if row['status'] == 'written' and p['sidecars'] == 'omit' and item['sidecar'] else 'absent' if row['status'] == 'written' else 'itemNotWritten'
                files['%s/%s.sidecar.json' % (OUTCOMES, item['id'])] = encode(no_sidecar_document(item, op, reason))
        tree = sorted(({'relativePath': path, 'sha256': legacy.sha(data), 'bytes': len(data), 'item': item_id, 'kind': kind} for path, data, item_id, kind in copies), key=lambda e: e['relativePath'].encode())
        files['tree.json'] = encode({'version': REPORT_VERSION, 'operation': op, 'files': tree, 'statement': 'Exactly the files this run created under organised/, sorted by path; every hash equals the capture of its item.'})
        files['organise-report.json'] = encode({'version': REPORT_VERSION, 'operation': op, 'runtime': RUNTIME, 'catalogue': p['catalogue'], 'sidecars': p['sidecars'], 'planSha256': legacy.sha(files['names-plan.json']),
                                                'items': table, 'counts': {'items': n, 'written': sum(1 for r in table if r['status'] == 'written'), 'refused': sum(1 for r in table if r['status'] == 'refused'),
                                                                           'failed': sum(1 for r in table if r['status'] == 'failed'), 'files': len(copies)},
                                                'statement': 'Per-item outcomes. Every copy is the capture byte for byte; verification recomputes the hashes, the paths and the tree from the retained captures.', 'losses': p['losses']})
    written = [r for r in table if r['status'] in ('written', 'planned')]
    manifest_items = [{'id': r['id'], 'status': 'ok' if r['status'] in ('written', 'planned') else 'fault', 'bytes': r['source']['bytes'], 'sha256': r['source']['sha256'], 'fault': r.get('fault'), 'sidecar': i['sidecar']} for r, i in zip(table, items)]
    manifest = wb.build_manifest(p, rows, manifest_items)
    by_id = {r['id']: r for r in table}
    for entry in manifest['entries']:
        r = by_id.get(entry.get('id'))
        if entry['role'] == 'item' and r is not None:
            entry.update(outcome=r['status'], artifactIndex=r['artifactIndex'])
    manifest['status'] = 'complete' if len(written) == len(table) and manifest['status'] == 'complete' else 'partial'
    manifest['writeCounts'] = {'items': len(table), 'written': sum(1 for r in table if r['status'] == 'written'), 'planned': sum(1 for r in table if r['status'] == 'planned'),
                               'refused': sum(1 for r in table if r['status'] == 'refused'), 'failed': sum(1 for r in table if r['status'] == 'failed')}
    manifest['slots'] = SLOT_TEXT[op]
    files['manifest.json'] = encode(manifest)
    if op == 'exportSidecar':
        files['sidecar-report.json'] = encode({'version': REPORT_VERSION, 'operation': op, 'runtime': RUNTIME, 'catalogue': p['catalogue'], 'transfer': p['transfer'], 'policies': p['policies'], 'setStatus': manifest['status'],
                                               'items': table, 'propertyMap': {prop: 'XMP:' + native for _, prop, _, native in xmpwrite.ROWS},
                                               'statement': 'Per-item outcomes with proof S: the serializer reproduces the sidecar, the hardened reader re-reads exactly the planned values and a fresh native listing carries exactly the expected XMP keys. Native agreement shows a literal is present and parseable, not that ExifTool interprets it.',
                                               'losses': p['losses']})
    return files, copies, table, {'manifest': manifest}


SLOT_TEXT = {'exportSidecar': 'artifact slot i is the i-th item of this manifest: its sidecar (text), or its outcome document; report documents follow the slots',
             'planNames': 'this operation publishes documents only: there are no per-item slots; the plan is names-plan.json',
             'organiseCopies': 'slots 0..N-1: item i\'s organised image or its outcome; slots N..2N-1: item i\'s sidecar copy or a noSidecar outcome; then names-plan.json, organise-report.json and tree.json at 2N, 2N+1 and 2N+2, then manifest.json'}


def report_names(p):
    if p['operation'] == 'exportSidecar':
        return ['manifest.json', 'sidecar-report.json']
    if p['operation'] == 'planNames':
        return ['names-plan.json', 'names.csv', 'manifest.json']
    return ['names-plan.json', 'organise-report.json', 'tree.json', 'manifest.json']


def artifacts(directory, p, table):
    """One artifact slot per item in manifest order (and per kind for organiseCopies), then the report documents."""
    op, out = p['operation'], []
    if op == 'exportSidecar':
        for r in table:
            if r['status'] == 'written':
                name = r['sidecar']['file']
                out.append({'file': str(directory / name), 'kind': 'text', 'sha256': r['sidecar']['sha256'], 'identity': {'kind': 'sidecar', 'format': 'xmp', 'item': r['id']}, 'losses': p['losses'],
                            'verificationScope': 'Proof S of this run: the serializer, the hardened reader and a fresh ExifTool listing, recomputed from the retained captures; no authenticity claim.'})
            else:
                name = '%s/%s.json' % (OUTCOMES, r['id'])
                out.append({'file': str(directory / name), 'kind': 'text', 'sha256': digest_of(directory, name), 'identity': {'kind': 'outcome', 'item': r['id'], 'image': False}})
    elif op == 'organiseCopies':
        for r in table:
            if r['status'] == 'written':
                out.append({'file': str(directory / r['output']['file']), 'kind': 'image', 'sha256': r['output']['sha256'], 'identity': {'kind': 'image', 'format': r['source']['container'], 'item': r['id'], 'relativePath': r['output']['relativePath']},
                            'losses': p['losses'], 'verificationScope': 'Exact byte copy: the SHA-256 equals the capture of the item; only the name and folder differ. No pixel decode and no authenticity claim.'})
            else:
                name = '%s/%s.json' % (OUTCOMES, r['id'])
                out.append({'file': str(directory / name), 'kind': 'text', 'sha256': digest_of(directory, name), 'identity': {'kind': 'outcome', 'item': r['id'], 'image': False}})
        for r in table:
            if r['status'] == 'written' and 'sidecar' in r:
                out.append({'file': str(directory / r['sidecar']['file']), 'kind': 'text', 'sha256': r['sidecar']['sha256'], 'identity': {'kind': 'sidecar', 'item': r['id'], 'relativePath': r['sidecar']['relativePath']}})
            else:
                name = '%s/%s.sidecar.json' % (OUTCOMES, r['id'])
                out.append({'file': str(directory / name), 'kind': 'text', 'sha256': digest_of(directory, name), 'identity': {'kind': 'noSidecar', 'item': r['id']}})
    for name in report_names(p):
        if name.endswith('.csv'):
            out.append({'file': str(directory / name), 'kind': 'table', 'sha256': digest_of(directory, name), 'identity': {'kind': 'table', 'format': wb.CSV_FORMAT, 'nullToken': wb.NULL_TOKEN}})
        else:
            record = {'file': str(directory / name), 'kind': 'text', 'sha256': digest_of(directory, name)}
            if name == 'names-plan.json':
                record['identity'] = {'kind': 'namePlan'}
            out.append(record)
    return out


# ---------------------------------------------------------------- the safe exact copier (organiseCopies)
class Unsafe(Exception):
    def __init__(self, code, message, **observed):
        super().__init__(message)
        self.code, self.message, self.observed = code, message, observed


DIRECTORY_FLAGS = os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0) | getattr(os, 'O_NOFOLLOW', 0)
DESCRIPTORS = all(f in os.supports_dir_fd for f in (os.open, os.mkdir, os.unlink)) and hasattr(os, 'O_DIRECTORY') and hasattr(os, 'O_NOFOLLOW')


def open_directories(base, parts, created, make=True):
    """The descriptor of ``base/parts``, reached one component at a time through directory descriptors (``O_DIRECTORY | O_NOFOLLOW``, relative ``mkdir``/``open``), so a component that is
    swapped for a link after it was opened cannot redirect a later write: the descriptor keeps naming the directory that was checked. A component that exists although this run did not create it
    (including a ``mkdir`` that lost a race), a link and a non-directory are the structured ``ORGANISE_PATH_UNSAFE``. The caller closes the descriptor."""
    descriptor = os.open(base, DIRECTORY_FLAGS)
    current = base
    try:
        for part in parts:
            current = current / part
            fresh = False
            if make:
                try:
                    os.mkdir(part, 0o755, dir_fd=descriptor)
                    created.add(current)
                    fresh = True
                except FileExistsError:
                    pass
            try:
                child = os.open(part, DIRECTORY_FLAGS, dir_fd=descriptor)
            except OSError:
                raise Unsafe('ORGANISE_PATH_UNSAFE', 'a path component is a link or not a directory, so nothing is written through it', path=str(current.relative_to(base)))
            os.close(descriptor)
            descriptor = child
            if make and not fresh and current not in created:
                raise Unsafe('ORGANISE_PATH_UNSAFE', 'a directory on the path exists although this run did not create it', path=str(current.relative_to(base)))
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def make_directories(base, parts, created):
    """The by-path form (a platform without directory descriptors): lstat each component, then create it."""
    current = base
    for part in parts:
        current = current / part
        try:
            info = os.lstat(current)
        except FileNotFoundError:
            try:
                os.mkdir(current, 0o755)
            except FileExistsError:
                raise Unsafe('ORGANISE_PATH_UNSAFE', 'a directory on the path exists although this run did not create it', path=str(current.relative_to(base)))
            created.add(current)
            continue
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
            raise Unsafe('ORGANISE_PATH_UNSAFE', 'a path component is a link or not a directory, so nothing is written through it', path=str(current.relative_to(base)))
        if current not in created:
            raise Unsafe('ORGANISE_PATH_UNSAFE', 'a directory on the path exists although this run did not create it', path=str(current.relative_to(base)))


def copy_exact(base, path, data, created):
    parts = path.split('/')
    if not DESCRIPTORS:
        return copy_exact_by_path(base, path, data, created)
    folder = open_directories(base, parts[:-1], created)
    try:
        try:
            fd = os.open(parts[-1], os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o644, dir_fd=folder)
        except FileExistsError:
            raise Unsafe('ORGANISE_TARGET_EXISTS', 'the target already exists, so nothing is replaced', path=path)
        except OSError as error:
            raise Unsafe('ORGANISE_PATH_UNSAFE', 'the target cannot be created without following a link: ' + str(error)[:120], path=path)
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
        try:
            check = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW, dir_fd=folder)
        except OSError as error:
            raise Unsafe('ORGANISE_COPY_MISMATCH', 'the copy cannot be read back from disk: ' + str(error)[:120], path=path)
        with os.fdopen(check, 'rb') as stream:
            found = stream.read(len(data) + 1)
        if found != data:
            raise Unsafe('ORGANISE_COPY_MISMATCH', 'the copy read back from disk differs from the capture', path=path)
    finally:
        os.close(folder)


def unlink_exact(base, path):
    """Remove one file this run created, through descriptors, so a directory that was swapped for a link meanwhile is never followed and nothing foreign is removed."""
    parts = path.split('/')
    try:
        if DESCRIPTORS:
            folder = open_directories(base, parts[:-1], set(), make=False)
            try:
                os.unlink(parts[-1], dir_fd=folder)
            finally:
                os.close(folder)
        else:
            os.unlink(base / path)
    except (OSError, Unsafe):
        pass


def copy_exact_by_path(base, path, data, created):
    parts = path.split('/')
    make_directories(base, parts[:-1], created)
    target = base / path
    try:
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0), 0o644)
    except FileExistsError:
        raise Unsafe('ORGANISE_TARGET_EXISTS', 'the target already exists, so nothing is replaced', path=path)
    except OSError as error:
        raise Unsafe('ORGANISE_PATH_UNSAFE', 'the target cannot be created without following a link: ' + str(error)[:120], path=path)
    with os.fdopen(fd, 'wb') as stream:
        stream.write(data)
    found = legacy.bounded(target, 'ORGANISE_COPY_MISMATCH', mediaset.item_limit(target))
    if found != data:
        raise Unsafe('ORGANISE_COPY_MISMATCH', 'the copy read back from disk differs from the capture', path=path)


def copy_tree(directory, copies, checkpoint):
    """Create every planned copy under ``organised/`` (units of image and sidecar are all or nothing); returns the recorded failures and foreign entries."""
    base = directory / ORGANISED
    created, failures = set(), []
    units = {}
    for path, data, item_id, kind in copies:
        units.setdefault(item_id, []).append((path, data))
    for item_id, parts in units.items():
        checkpoint()
        done = []
        try:
            for path, data in parts:
                copy_exact(base, path, data, created)
                done.append(path)
        except Unsafe as error:
            for path in done:
                unlink_exact(base, path)
            failures.append({'item': item_id, 'code': error.code, 'message': error.message, **error.observed})
    return failures


def foreign_entries(directory, produced):
    """Every entry under ``organised/`` that this run did not create (an injected race), with its kind and identity."""
    base = directory / ORGANISED
    found = []
    produced = set(produced)

    def walk(folder, relative):
        for name in sorted(os.listdir(folder), key=os.fsencode):
            path, rel = folder / name, (relative + '/' + name) if relative else name
            info = os.lstat(path)
            if stat.S_ISLNK(info.st_mode):
                found.append({'path': rel, 'kind': 'symlink', 'target': os.readlink(path)})
            elif stat.S_ISDIR(info.st_mode):
                if rel not in produced_dirs:
                    found.append({'path': rel, 'kind': 'directory'})
                walk(path, rel)
            elif stat.S_ISREG(info.st_mode):
                if rel not in produced:
                    found.append({'path': rel, 'kind': 'file', 'bytes': info.st_size, 'sha256': legacy.sha(legacy.bounded(path, limit=mediaset.item_limit(path)))})
            else:
                found.append({'path': rel, 'kind': 'special'})
    produced_dirs = {'/'.join(p.split('/')[:k]) for p in produced for k in range(1, len(p.split('/')))}
    if base.is_dir():
        walk(base, '')
    return found


def check_tree(directory, copies, foreign):
    """Proof C on the run directory: nothing but the produced files, their directories and the recorded foreign entries exists under ``organised/``; no link, no alias of a capture."""
    base = directory / ORGANISED
    produced = {path: data for path, data, _, _ in copies}
    allowed_dirs = {'/'.join(p.split('/')[:k]) for p in produced for k in range(1, len(p.split('/')))}
    recorded = {f['path']: f for f in foreign}
    if not base.is_dir() or base.is_symlink():
        fail('VERIFICATION_FAILED', 'organised/ is not a real directory', ORGANISED)
    seen = set()

    def walk(folder, relative):
        for name in sorted(os.listdir(folder), key=os.fsencode):
            path, rel = folder / name, (relative + '/' + name) if relative else name
            info = os.lstat(path)
            if rel in recorded:
                entry = recorded[rel]
                if stat.S_ISLNK(info.st_mode):
                    ok = entry['kind'] == 'symlink' and os.readlink(path) == entry['target']
                elif stat.S_ISDIR(info.st_mode):
                    ok = entry['kind'] == 'directory'
                    if ok:
                        seen.add(rel)
                        walk(path, rel)
                        continue
                else:
                    ok = entry['kind'] == 'file' and stat.S_ISREG(info.st_mode) and legacy.sha(legacy.bounded(path, limit=mediaset.item_limit(path))) == entry['sha256']
                if not ok:
                    fail('ORGANISE_COPY_MISMATCH', 'a recorded foreign entry under organised/ differs from its record', ORGANISED + '/' + rel)
                seen.add(rel)
            elif stat.S_ISLNK(info.st_mode):
                fail('ORGANISE_COPY_MISMATCH', 'a link exists under organised/', ORGANISED + '/' + rel)
            elif stat.S_ISDIR(info.st_mode):
                if rel not in allowed_dirs:
                    fail('ORGANISE_COPY_MISMATCH', 'an extra directory exists under organised/', ORGANISED + '/' + rel)
                seen.add(rel)
                walk(path, rel)
            elif stat.S_ISREG(info.st_mode):
                if rel.endswith(METADATA) and rel[:-len(METADATA)] in produced:          # the framework's publication metadata beside a published artifact
                    seen.add(rel)
                    continue
                if rel not in produced:
                    fail('ORGANISE_COPY_MISMATCH', 'an extra file exists under organised/', ORGANISED + '/' + rel)
                if info.st_nlink > 1:
                    fail('ORGANISE_COPY_MISMATCH', 'a copy is hard-linked', ORGANISED + '/' + rel)
                if legacy.bounded(path, limit=mediaset.item_limit(path)) != produced[rel]:
                    fail('ORGANISE_COPY_MISMATCH', 'a copy differs from the capture of its item', ORGANISED + '/' + rel)
                seen.add(rel)
            else:
                fail('ORGANISE_COPY_MISMATCH', 'a special file exists under organised/', ORGANISED + '/' + rel)
    walk(base, '')
    if not (set(produced) | set(recorded)) <= seen:
        fail('ORGANISE_COPY_MISMATCH', 'a planned copy is missing under organised/', ORGANISED, missing=sorted((set(produced) | set(recorded)) - seen)[:8])


# ---------------------------------------------------------------- run
def run_stage(directory, stage, command, names, timeout):
    return editing.run_stage(directory, stage, command, names, timeout)


def stage_command(script, stage, names):
    return editing.stage_command(script, stage, names)


def checkpoint_of(timeout):
    def checkpoint():
        if cancellation_requested():
            fail('RUNNER_CANCELLED', 'metadata work cancelled')
        remaining_timeout(timeout)
    return checkpoint


def run(document, directory, *, executable=None, timeout=300):
    import math
    p = plan(document)
    executable = executable or os.environ.get('SCHEMAXIS_EXIFTOOL') or shutil.which('exiftool')
    if not executable or not Path(executable).is_absolute() or not os.access(executable, os.R_OK) or not Path(executable).is_file():
        fail('INTERPRETER_NOT_FOUND', 'configure an absolute ExifTool 13.55 script path (--exiftool)')
    if not Path(PERL).is_file() or not os.access(PERL, os.X_OK):
        fail('INTERPRETER_NOT_FOUND', 'ExifTool needs the system Perl at ' + PERL)
    if os.name != 'posix':
        fail('UNSUPPORTED_PLATFORM', 'native resource caps require POSIX')
    if type(timeout) not in (int, float) or not math.isfinite(timeout) or not 0 < timeout <= 3600:
        fail('INVALID_ARGUMENT', 'timeout must be finite in (0,3600]')
    executable = str(executable)
    directory = Path(directory).absolute()
    if directory.exists() or directory.is_symlink():
        fail('OUTPUT_EXISTS', 'select a fresh output directory', str(directory))
    directory.mkdir(parents=True)
    atomic_json(directory / 'authored.json', document)
    atomic_json(directory / 'plan.json', p)
    atomic_json(directory / 'result.json', {'status': 'incomplete', 'verified': False})
    checkpoint = checkpoint_of(timeout)
    op = p['operation']
    try:
        with execution_deadline(timeout):
            checkpoint()
            rows, targets, signature = wb.collect(p)
            (directory / CAPTURED).mkdir()
            seen, running, entries = {}, [0], []
            for order, target in enumerate(targets, 1):
                checkpoint()
                entry, files = wb.capture_target(p, order, target, seen, running)
                for name, data in files.items():
                    (directory / name).write_bytes(data)
                entries.append(entry)
            if signature is not None:
                _, _, after_signature = wb.collect_signature(p)
                if after_signature != signature:
                    fail('MEDIA_FOLDER_CHANGED', 'the media folder changed while its items were captured; run again when it is stable', '$.media.folder.path',
                         changed=sorted({k for k in set(signature) | set(after_signature) if signature.get(k) != after_signature.get(k)})[:20])
            captured = {'source': wb.source_set(p, rows, signature), 'rows': rows, 'items': entries}
            inputs = capture_plan(p, directory)
            if inputs:
                captured['inputs'] = inputs
            atomic_json(directory / 'captures.json', captured)
            ctx = Context(p, directory, captured)
            items = admit(directory, p, captured)
            for item in items:
                if item['sidecar']:
                    item['sidecar_path'] = str(directory / item['sidecar']['file'])
            if not any(i['status'] == 'ok' for i in items):
                finish_without_success(directory, p, rows, items, ctx, 'no item of the media set could be admitted')
            names = native_names(items)
            runtime = None
            for stage in ('version', 'libraries', 'modules', 'before'):
                checkpoint()
                run_stage(directory, stage, stage_command(executable, stage, names), names if stage == 'before' else [], remaining_timeout(timeout))
                if stage == 'version':
                    legacy.qualified_runtime(directory)
                if stage == 'modules':
                    runtime = legacy.runtime_identity(directory, executable, checkpoint)
            before_bytes = legacy.bounded(directory / 'before.stdout', limit=listing.MAX_STDOUT + 1)
            if legacy.bounded(directory / 'before.stderr', limit=legacy.LOG_LIMIT):
                fail('NATIVE_OBSERVATION_MISMATCH', 'the native listing of the captures wrote to stderr', 'before')
            natives = wb.apply_native(p, items, before_bytes)
            plan_ = prepare(p, items, ctx)
            if not any(i['status'] == 'ok' for i in items):
                finish_without_success(directory, p, rows, items, ctx, 'every item was refused before anything was written', plan_)
            after_names, after = [], None
            if op == 'exportSidecar':
                (directory / STAGE).mkdir(mode=0o700)
                for item in items:
                    if item['status'] == 'ok':
                        (directory / stage_file(item['id'])).write_bytes(item['export']['bytes'])
                        after_names.append(stage_file(item['id']))
                checkpoint()
                run_stage(directory, 'after', stage_command(executable, 'after', after_names), after_names, remaining_timeout(timeout))
                if legacy.bounded(directory / 'after.stderr', limit=legacy.LOG_LIMIT):
                    fail('NATIVE_OBSERVATION_MISMATCH', 'the native listing of the produced sidecars wrote to stderr', 'after')
                after = dict(zip(after_names, listing.parse(legacy.bounded(directory / 'after.stdout', limit=listing.MAX_STDOUT + 1), after_names)))
            checkpoint()
            if legacy.runtime_identity(directory, executable, checkpoint) != runtime:
                fail('RUNTIME_CHANGED', 'ExifTool, Perl or a dependency changed during the run')
            for entry in entries:
                if entry['fault'] is None and legacy.stream_capture(entry['source'], mediaset.item_limit(entry['source']), 'PHOTO_CHANGED', location='$.media')['sha256'] != entry['sha256']:
                    fail('PHOTO_CHANGED', 'a source item changed during the native run', '$.media', photo=entry['id'])
            atomic_json(directory / 'runtime.json', {'executable': executable, **runtime})
            organise = {'failures': [], 'foreign': []}
            (directory / OUTCOMES).mkdir(exist_ok=True)
            if op == 'organiseCopies':
                _, planned_copies, _, _ = build(p, rows, items, plan_, natives, ctx, None, None, directory)
                (directory / ORGANISED).mkdir()
                organise['failures'] = copy_tree(directory, planned_copies, checkpoint)
                failed_items = {f['item'] for f in organise['failures']}
                produced = [path for path, _, item_id, _ in planned_copies if item_id not in failed_items]
                organise['foreign'] = foreign_entries(directory, produced)
                atomic_json(directory / 'organise-runtime.json', organise)
            files, copies, table, _ = build(p, rows, items, plan_, natives, ctx, after, organise if op == 'organiseCopies' else None, directory)
            if not any(r['status'] in ('written', 'planned') for r in table):
                finish_without_success(directory, p, rows, items, ctx, 'no item was written', plan_, files)
            publish(directory, p, files, table, after_names)
            evidence = {n: digest_of(directory, n, limit_of(n)) for n in sorted(evidence_names(p, captured, bool(after_names)))}
            atomic_json(directory / 'verification.json', {'executable': executable, 'runtime': RUNTIME, 'planSha256': plan_hash(p), 'artifacts': artifacts(directory, p, table), 'evidence': evidence})
            result = verify(directory, require_result=False, executable=executable)
            checkpoint()
            result['status'] = 'succeeded'
            atomic_json(directory / 'result.json', result)
            return result
    except Exception as error:
        if not isinstance(error, SchemaxisError):
            try:
                fail('NATIVE_EXECUTION_FAILED', str(error))
            except SchemaxisError as wrapped:
                error = wrapped
        atomic_json(directory / 'result.json', {'status': 'failed', 'verified': False, 'fault': error.fault.to_dict()})
        raise error


def publish(directory, p, files, table, after_names):
    """Write the derived documents; a staged sidecar is moved into ``sidecars/`` when published and into ``rejected/`` when its anchoring failed."""
    status = {r['id']: r['status'] for r in table}
    for sub in (SIDECARS, REJECTED):
        if p['operation'] == 'exportSidecar':
            (directory / sub).mkdir(exist_ok=True)
    for name, data in files.items():
        if name.startswith(SIDECARS + '/'):
            continue
        (directory / name).parent.mkdir(parents=True, exist_ok=True)
        (directory / name).write_bytes(data)
    for name in after_names:
        item_id = Path(name).stem
        source = directory / name
        target = directory / (SIDECARS if status[item_id] == 'written' else REJECTED) / (item_id + '.xmp')
        os.replace(source, target)
    if (directory / STAGE).is_dir():
        os.rmdir(directory / STAGE)
    for sub in (SIDECARS, REJECTED):
        folder = directory / sub
        if folder.is_dir() and not any(folder.iterdir()):
            os.rmdir(folder)


def finish_without_success(directory, p, rows, items, ctx, reason, plan_=None, files=None):
    """Every item was refused or failed: write the truthful manifest and outcomes, then fail the run (no success publication)."""
    manifest_items = [{'id': i['id'], 'status': 'fault', 'bytes': i['bytes'], 'sha256': i['sha256'], 'fault': i['fault'], 'sidecar': i['sidecar']} for i in items]
    manifest = wb.build_manifest(p, rows, manifest_items)
    (directory / OUTCOMES).mkdir(exist_ok=True)
    (directory / 'manifest.json').write_bytes(encode(manifest))
    for item in items:
        (directory / OUTCOMES / (item['id'] + '.json')).write_bytes(encode(outcome_document({**item, 'status': 'refused'}, p['operation'])))
    fail('NO_USABLE_ITEMS', reason + '; manifest.json and outcomes/ list every item and its fault', '$.media', items=len(items), firstFaults=[i['fault'] for i in items[:3]])


# ---------------------------------------------------------------- verification
def membership(directory, p, captured, table, after_stage):
    """Nothing but the owned evidence, the published slots and their companions may exist in the run directory."""
    from schemaxis.run_paths import MANIFEST
    top = {n for n in evidence_names(p, captured, after_stage) if '/' not in n}
    top |= set(report_names(p)) | {'verification.json', 'result.json', 'schema.snapshot.json', MANIFEST, 'job.json'} | {n + '.metadata.json' for n in report_names(p)}
    subdirs = (CAPTURED, SIDECARS, OUTCOMES, REJECTED, ORGANISED, INPUTS)
    for path in directory.iterdir():
        if path.name in ('.dispatch',) + subdirs:
            if path.is_symlink() or not path.is_dir():
                fail('VERIFICATION_FAILED', 'owned member is not a directory', path.name)
        elif path.name not in top or path.is_symlink() or not path.is_file():
            fail('VERIFICATION_FAILED', 'unexpected or nonregular retained member', path.name)
    expected = {CAPTURED: sorted(Path(n).name for n in evidence_names(p, captured, False) if n.startswith(CAPTURED + '/')),
                SIDECARS: sorted(n for r in table if r['status'] == 'written' and p['operation'] == 'exportSidecar' for n in (r['id'] + '.xmp', r['id'] + '.xmp.metadata.json')),
                REJECTED: sorted(r['id'] + '.xmp' for r in table if r['status'] == 'failed' and p['operation'] == 'exportSidecar'),
                OUTCOMES: sorted(n for r in table for n in outcome_names(p, r)),
                INPUTS: sorted(Path(n).name for n in evidence_names(p, captured, False) if n.startswith(INPUTS + '/'))}
    for sub, names in expected.items():
        folder = directory / sub
        present = sorted(x.name for x in folder.iterdir()) if folder.is_dir() else []
        required = [n for n in names if not n.endswith('.metadata.json')]
        if not set(required) <= set(present) <= set(names) | {n + '.metadata.json' for n in names}:
            fail('VERIFICATION_FAILED', 'retained %s membership differs' % sub, sub, expected=required[:8], observed=present[:8])
        for x in folder.iterdir() if folder.is_dir() else ():
            if x.is_symlink() or not x.is_file():
                fail('VERIFICATION_FAILED', 'a retained member is not a regular file', sub + '/' + x.name)


def outcome_names(p, row):
    names = []
    if p['operation'] == 'planNames':
        return names                    # a plan publishes documents only: refused items are rows of names-plan.json, not slots
    if row['status'] not in ('written', 'planned'):
        names.append(row['id'] + '.json')
    if p['operation'] == 'organiseCopies' and not (row['status'] == 'written' and 'sidecar' in row):
        names.append(row['id'] + '.sidecar.json')
    return names + [n + '.metadata.json' for n in names]


def check_stages(directory, retained_executable, specs):
    """Every retained native stage was launched by the trusted launcher with the exact command, finished cleanly and read exactly the bytes it names."""
    for stage, names in specs:
        command = stage_command(retained_executable, stage, names)
        path = directory / (stage + '-launcher.py')
        submission = read_json(directory, stage + '-submission.json')
        interpreter = submission.get('interpreter', {}).get('executable') if isinstance(submission, dict) and isinstance(submission.get('interpreter'), dict) else None
        if not isinstance(interpreter, str) or not Path(interpreter).is_absolute() or submission.get('nativeCommand') != [interpreter, str(path)] or type(submission.get('exitCode')) is not int or submission['exitCode'] != 0:
            fail('VERIFICATION_FAILED', 'native command/completion differs', stage)
        if legacy.bounded(path).decode() != editing.launcher(stage, command, names):
            fail('VERIFICATION_FAILED', 'trusted native launcher differs', stage)
        if not legacy.same_json(read_json(directory, stage + '-inputs.json'), {'files': {n: digest_of(directory, n if not n.startswith(STAGE + '/') else stage_path_of(directory, n), limit_of(n)) for n in names}}):
            fail('VERIFICATION_FAILED', 'native input binding differs', stage)


def verify(directory, require_result=True, *, executable=None):
    """Recompute every proof from the retained bytes, rebuild every publication, and replay the native listings with a trusted runtime."""
    directory = Path(directory).absolute()
    try:
        with execution_deadline(wb.VERIFY_TIMEOUT):
            p = plan(legacy.read(directory, 'authored.json'))
            op = p['operation']
            receipt = read_json(directory, 'verification.json')
            if not isinstance(receipt, dict) or set(receipt) != {'executable', 'runtime', 'planSha256', 'artifacts', 'evidence'} or not isinstance(receipt['evidence'], dict):
                fail('VERIFICATION_FAILED', 'native receipt member set differs')
            if not legacy.same_json(read_json(directory, 'plan.json'), p) or receipt['planSha256'] != plan_hash(p):
                fail('VERIFICATION_FAILED', 'effective plan differs from the authored input or receipt')
            if require_result and read_json(directory, 'result.json').get('status') != 'succeeded':
                fail('INCOMPLETE_EXECUTION', 'metadata work did not complete')
            captured = read_json(directory, 'captures.json')
            if not isinstance(captured, dict) or set(captured) - {'inputs'} != {'source', 'rows', 'items'} or not isinstance(captured['items'], list) or not isinstance(captured['rows'], list):
                fail('VERIFICATION_FAILED', 'capture record member set differs')
            ctx = Context(p, directory, captured)
            items = admit(directory, p, captured)
            for item in items:
                if item['sidecar']:
                    item['sidecar_path'] = str(directory / item['sidecar']['file'])
            before_bytes = legacy.bounded(directory / 'before.stdout', limit=listing.MAX_STDOUT + 1)
            if legacy.bounded(directory / 'before.stderr', limit=legacy.LOG_LIMIT):
                fail('VERIFICATION_FAILED', 'the native listing of the captures wrote to stderr', 'before')
            names_before = native_names(items)
            natives = wb.apply_native(p, items, before_bytes)
            plan_ = prepare(p, items, ctx)
            after_names, after, after_bytes = [], None, None
            if op == 'exportSidecar':
                after_names = [stage_file(i['id']) for i in items if i['status'] == 'ok']
                after_bytes = legacy.bounded(directory / 'after.stdout', limit=listing.MAX_STDOUT + 1)
                if legacy.bounded(directory / 'after.stderr', limit=legacy.LOG_LIMIT):
                    fail('VERIFICATION_FAILED', 'the native listing of the produced sidecars wrote to stderr', 'after')
                after = dict(zip(after_names, listing.parse(after_bytes, after_names)))
                for item in items:                  # S(1), S(2): from the retained bytes, before any digest or listing comparison
                    if item['status'] != 'ok':
                        continue
                    for sub in (SIDECARS, REJECTED):
                        found = directory / sub / (item['id'] + '.xmp')
                        if found.is_file():
                            check_sidecar_bytes(item, legacy.bounded(found, limit=mediaset.ITEM_BYTES), sub + '/' + item['id'] + '.xmp')
                            problems = native_problems(item['export']['model'], after.get(stage_file(item['id'])))      # S(3): judged here, so a tampered listing is named before any structural comparison
                            if sub == SIDECARS and problems:
                                fail('SIDECAR_ANCHOR_MISMATCH', 'the retained native listing of a published sidecar does not carry exactly the expected XMP keys and values', 'after', item=item['id'], problems=problems[:4])
                            break
                    else:
                        fail('VERIFICATION_FAILED', 'a candidate sidecar is neither published nor rejected', item['id'])
            organise = None
            if op == 'organiseCopies':
                organise = read_json(directory, 'organise-runtime.json')
                if not isinstance(organise, dict) or set(organise) != {'failures', 'foreign'}:
                    fail('VERIFICATION_FAILED', 'organise runtime record member set differs')
            files, copies, table, extras = build(p, captured['rows'], items, plan_, natives, ctx, after, organise, directory)
            if op == 'organiseCopies':
                check_tree(directory, copies, organise['foreign'])
            for name, content in files.items():
                found = legacy.bounded(directory / name, limit=limit_of(name))
                if found != content:
                    if name == 'names-plan.json':
                        fail('NAME_PLAN_STALE', 'the retained name plan differs from the plan recomputed from the retained captures and rule', name)
                    fail('VERIFICATION_FAILED', 'published file differs from independently derived evidence', name)
            membership(directory, p, captured, table, bool(after_names))
            retained_executable = receipt['executable']
            if not isinstance(retained_executable, str) or not Path(retained_executable).is_absolute():
                fail('VERIFICATION_FAILED', 'native executable identity must be absolute')
            specs = [('version', []), ('libraries', []), ('modules', []), ('before', names_before)] + ([('after', after_names)] if after_names else [])
            check_stages(directory, retained_executable, specs)
            if receipt['runtime'] != legacy.qualified_runtime(directory, 'VERIFICATION_FAILED'):
                fail('VERIFICATION_FAILED', 'require qualified ExifTool 13.55 runtime identity')
            wb.check_runtime_record(directory, retained_executable)
            if not legacy.same_json(receipt['artifacts'], artifacts(directory, p, table)):
                fail('VERIFICATION_FAILED', 'publication membership/digest differs')
            wanted = evidence_names(p, captured, bool(after_names))
            if set(receipt['evidence']) != wanted:
                fail('VERIFICATION_FAILED', 'native evidence membership differs')
            for n in wanted:
                if digest_of(directory, n if not n.startswith(STAGE + '/') else stage_path_of(directory, n), limit_of(n)) != receipt['evidence'][n]:
                    fail('VERIFICATION_FAILED', 'retained native evidence differs', n)
            trusted = wb.trusted_runtime(executable)
            if trusted is None:
                fail('NATIVE_REPLAY_UNAVAILABLE', 'the native listings cannot be verified without a configured trusted ExifTool 13.55 runtime; the proofs re-derived from the retained bytes are consistent but the native anchoring is not verified', '$.runtime.exiftool',
                     independentVerified=True, nativeVerified=False, recovery='use --exiftool, schemaxis configure exiftool, or SCHEMAXIS_EXIFTOOL (a receipt executable is never launched)')
            editing.same_listing(editing.fresh_listing({n: legacy.bounded(directory / n, limit=mediaset.item_limit(n)) for n in names_before}, names_before, trusted, 'before'), before_bytes, 'before')
            if after_names:
                data = {n: legacy.bounded(directory / stage_path_of(directory, n), limit=mediaset.item_limit(n)) for n in after_names}
                fresh = fresh_after(data, after_names, trusted)
                if fresh != after_bytes:
                    fail('SIDECAR_ANCHOR_MISMATCH', 'the fresh native listing of the retained sidecars differs from the retained listing', 'after')
            manifest = extras['manifest']
            fresh = {'verified': True, 'artifacts': len(receipt['artifacts']), 'runtime': RUNTIME, 'operation': op, 'items': len(table), 'written': sum(1 for r in table if r['status'] == 'written'),
                     'planned': sum(1 for r in table if r['status'] == 'planned'), 'refused': sum(1 for r in table if r['status'] == 'refused'), 'failed': sum(1 for r in table if r['status'] == 'failed'),
                     'setStatus': manifest['status'], 'manifestSha256': legacy.sha(files['manifest.json']), 'publicationSha256': {n: legacy.sha(c) for n, c in sorted(files.items())},
                     'nativeReplay': 'fresh-replay-matched', 'proofs': PROOFS[op], 'observedMetadataOnly': True, 'privacyCertified': False, 'humanReviewRequired': True}
            if require_result:
                retained = read_json(directory, 'result.json')
                if not legacy.same_json({k: v for k, v in retained.items() if k != 'nativeReplay'}, {**{k: v for k, v in fresh.items() if k != 'nativeReplay'}, 'status': 'succeeded'}):
                    fail('VERIFICATION_FAILED', 'retained result differs from independent reopening')
            return fresh
    except SchemaxisError as error:
        if error.fault.code in ('VERIFICATION_FAILED', 'INCOMPLETE_EXECUTION', 'NATIVE_REPLAY_UNAVAILABLE', 'RUNNER_CANCELLED', 'RUNNER_TIMED_OUT', 'SIDECAR_NOT_REPRODUCIBLE', 'SIDECAR_ANCHOR_MISMATCH',
                                  'NAME_PLAN_STALE', 'ORGANISE_COPY_MISMATCH', 'ORGANISE_PATH_UNSAFE', 'ORGANISE_TARGET_EXISTS'):
            raise
        fail('VERIFICATION_FAILED', 'retained evidence violates its contract (' + error.fault.code + ': ' + error.fault.message + ')', error.fault.location, cause=error.fault.to_dict())
    except (OSError, ValueError, KeyError, TypeError, IndexError, AttributeError, UnicodeDecodeError, RecursionError) as error:
        fail('VERIFICATION_FAILED', 'invalid retained evidence: ' + str(error))


PROOFS = {'exportSidecar': ['serializer', 'readerReread', 'nativeAnchor'], 'planNames': ['namePlan'], 'organiseCopies': ['namePlan', 'exactCopy']}


def fresh_after(data, names, executable):
    """A fresh fixed listing of the retained sidecar bytes with the trusted runtime."""
    scratch = Path(tempfile.mkdtemp(prefix='schemaxis-exiftool-'))
    try:
        (scratch / STAGE).mkdir()
        for name in names:
            (scratch / name).write_bytes(data[name])
        run_stage(scratch, 'version', stage_command(executable, 'version', []), [], remaining_timeout(wb.VERIFY_TIMEOUT))
        if legacy.bounded(scratch / 'version.stdout', 'NATIVE_REPLAY_UNAVAILABLE', 4096).decode('utf-8', 'replace') != '13.55\n':
            fail('NATIVE_REPLAY_UNAVAILABLE', 'the configured ExifTool is not the pinned 13.55 production release', 'version', independentVerified=True)
        run_stage(scratch, 'after', stage_command(executable, 'after', names), names, remaining_timeout(wb.VERIFY_TIMEOUT))
        if legacy.bounded(scratch / 'after.stderr', limit=legacy.LOG_LIMIT):
            fail('VERIFICATION_FAILED', 'the fresh native replay wrote to stderr', 'after')
        return legacy.bounded(scratch / 'after.stdout', limit=listing.MAX_STDOUT + 1)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
