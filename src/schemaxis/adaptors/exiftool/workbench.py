"""Metadata workbench read family: inspectMetadata, auditMetadata and compareMetadata over a bounded media set.

Every operation shares one pipeline. Items are captured into the run (explicit list or one declared folder, with a complete
inclusion/exclusion manifest and per-item faults), each captured file is read by the independent standard-library locators and decoders
into typed catalogue records, and the pinned ExifTool 13.55 then lists the same captured bytes with a fixed argument list. Every
independent value is anchored against that native listing: an anchor mismatch refuses the item, it never downgrades a proof level.

Proof levels: ``independent`` values were decoded from the captured bytes by the host reader (and agreed with ExifTool when produced);
``native-observed`` values are ExifTool's own listing of those bytes. Verification re-derives independent values from the retained bytes
and replays the native listing with the configured trusted runtime; without that runtime a native listing is never reported verified.
A same-engine replay is reproducibility, not independent semantic truth. Nothing here certifies when, where or by whom a photo was taken.
"""
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
import time

from schemaxis.adaptors.exiftool import e5locate, e5profiles, adaptor as legacy, audit as auditing, catalogue, containers, e3read, e3reports, listing, mediaset, options, records
from schemaxis.artifacts import atomic_json
from schemaxis.configuration import executable as configured_executable
from schemaxis.core.declarations import validate_arguments
from schemaxis.core.faults import Fault, SchemaxisError
from schemaxis.dispatch import cancellation_requested, execution_deadline, remaining_timeout
from schemaxis.errors import fail, keys
from schemaxis.native_command import execute

OPERATIONS = legacy.WORKBENCH_OPERATIONS
VERSION = legacy.VERSION
RUNTIME = legacy.RUNTIME
PERL = legacy.PERL
PLAN_VERSION = 'schemaxis.exiftool.workbench.plan/1'
METADATA_VERSION = 'schemaxis.exiftool.workbench.metadata/1'
MANIFEST_VERSION = 'schemaxis.exiftool.media-manifest/1'
CSV_FORMAT = legacy.CSV_FORMAT
NULL_TOKEN = legacy.NULL_TOKEN
MAX_TEXT = 1024
STAGES = ('version', 'libraries', 'modules', 'listing', 'repeat')
CAPTURED = 'captured'
JSON_LIMIT = 64 * 1024 * 1024
VERIFY_TIMEOUT = 300
GPS_TOLERANCE = 300
PROFILES, FIELDS, OPTIONS, DECLARATIONS = options.PROFILES, options.FIELDS, options.OPTIONS, options.DECLARATIONS
REVIEW = ('Observed metadata only. Independent values were decoded from the captured bytes by the host reader and anchored against the pinned ExifTool listing; '
          'native-observed values are ExifTool\'s own report of those bytes. A camera or editor can record a wrong clock, zone, place, owner or description, and several '
          'sources in one file can disagree: nothing here certifies when, where or by whom a photograph was taken, and no source is preferred where they differ. '
          'A person must review conflicts, unreadable values and privacy-relevant fields before sharing or relying on a file.')
LOSSES = [
    'Containers: baseline, extended, progressive and other JFIF/Exif JPEG files (entropy data is scanned for markers only, never decoded) and standalone XMP sidecar files. No pixel decode, image-quality, face or content claim is made; other containers (TIFF, PNG, WebP, HEIC, RAW, video) are not located yet and are excluded or faulted per item.',
    'Fields: only the catalogued fields (see the field catalogue). Every other tag, MakerNotes, thumbnails, ICC, C2PA/JUMBF and extended XMP stay unassessed by the independent reader; the optional native listing shows what ExifTool reports for them at the native-observed level only.',
    'Presence is explicit: present, absent (the family was understood and has no value), unreadable (present but malformed), unsupported, ambiguous (duplicate locations or conflicting sources) and unassessed (not requested) are different states and are never merged or replaced by filesystem times or inferred values.',
    'Concordance between EXIF, IPTC and XMP sources is the literal equality of canonical values. It is not Metadata Working Group reconciliation, no source is preferred, and a disagreement is reported as an ambiguous field with every source value.',
    'IPTC text is decoded only under an explicit coded character set: UTF-8 (1:90 ESC % G) is decoded, 7-bit ASCII is read without 1:90, other sets and non-ASCII text without 1:90 are reported rather than guessed. Exif text is ASCII or UTF-8 as found; XMP must be UTF-8 and may not carry a DOCTYPE or entity declaration.',
    'Times are camera-recorded wall times without a zone; a UTC instant is derived only where the same file records an explicit offset. GPS values are reported as the file records them (signed decimal degrees from the reference letters, altitude with its sea-level reference, the recorded datum text): no datum conversion, WGS-84 inference, reverse geocoding or place verification is made.',
    'Read-only: originals are never written, renamed, rotated or stripped. Hashes identify the bytes captured for this run, not their origin, and a coherent rewrite of every retained record verifies as consistency, not authenticity. This is not privacy certification: a clean audit does not mean a file is safe to share.',
    'ExifTool 13.55 (production release) runs through the system Perl with a clean fixed environment, one thread, no configuration, no authored option or tag name, and the filesystem/system tag group excluded so two fresh processes list the same captured bytes identically.']


# ---------------------------------------------------------------- planning
def digest_text(data): return hashlib.sha256(data).hexdigest()


def catalogue_digest(version=catalogue.VERSION):
    return catalogue.digest(version)


def plan_catalogue(p):
    """The catalogue version a plan names; only the two known versions exist, and anything else fails closed."""
    return p['catalogue']['version']


def plan(document):
    keys(document, ('version', 'operation', *sorted(set().union(*OPTIONS.values()))), '$')
    if document.get('version') != VERSION:
        fail('UNSUPPORTED_VERSION', 'expected ' + VERSION, '$.version')
    operation = document.get('operation')
    if operation not in OPERATIONS:
        fail('UNKNOWN_OPERATION', 'select ' + ', '.join(OPERATIONS), '$.operation')
    options = OPTIONS[operation]
    extra = sorted(set(document) - {'version', 'operation'} - set(options))
    if extra:
        fail('UNKNOWN_ARGUMENT', 'unsupported keys for ' + operation, '$', keys=extra)
    p = validate_arguments(options, {k: v for k, v in document.items() if k in options})
    media = mediaset.plan_media(p['media'])
    if operation in E3_OPERATIONS:
        return plan_e3(operation, p, media)
    profiles = [x for x in PROFILES if x in p.get('profiles', [])]
    chosen = set(catalogue.profile_fields(profiles))
    audit_block = compare_block = None
    if operation == 'auditMetadata':
        require = [f for f in FIELDS if f in p.get('require', [])]
        rules = [r for r in auditing.RULES if r in p['rules']] if 'rules' in p else [r for r in auditing.RULES if r != 'requiredFields' or require]
        if 'requiredFields' in rules and not require:
            fail('INVALID_AUDIT', 'requiredFields needs at least one required field', '$.require')
        if require and 'requiredFields' not in rules:
            fail('INVALID_AUDIT', 'require has no effect unless the requiredFields rule is selected', '$.require')
        if 'gpsToleranceSeconds' in p and 'timePlausibility' not in rules:
            fail('INVALID_AUDIT', 'gpsToleranceSeconds has no effect unless the timePlausibility rule is selected', '$.gpsToleranceSeconds')
        chosen |= set(require)
        for rule in rules:
            chosen |= set(auditing.RULE_FIELDS.get(rule, ()))
        audit_block = {'rules': rules, 'require': require, 'gpsToleranceSeconds': p.get('gpsToleranceSeconds', GPS_TOLERANCE)}
    if operation == 'compareMetadata':
        if not mediaset.IDENTIFIER.fullmatch(p['baseline']):
            fail('INVALID_PHOTO_ID', 'use an ASCII letter followed by up to 31 letters, digits or underscores', '$.baseline', value=p['baseline'][:64])
        if media['kind'] == 'items' and p['baseline'] not in [i['id'] for i in media['items']]:
            fail('INVALID_BASELINE', 'the baseline must be one of the authored item IDs', '$.baseline', value=p['baseline'])
        chosen |= set(p.get('fields', []))
        compare_block = {'baseline': p['baseline']}
    version = catalogue.VERSION_MWG if p.get('creatorInterpretation') == 'mwg' else catalogue.VERSION   # absent or literal: the exact E1 plan
    fields = [f for f in FIELDS if f in chosen]
    if not fields:
        fail('INVALID_ARGUMENT', 'select at least one profile or field to assess', '$.profiles')
    # derived fields need their inputs assessed so the published record can show them
    return {'version': PLAN_VERSION, 'operation': operation, 'media': media, 'profiles': profiles, 'fields': fields,
            'nativeListing': bool(p.get('nativeListing', False)), 'audit': audit_block, 'compare': compare_block,
            'settings': {'nativeArguments': listing.FIXED, 'threads': 1, 'userConfiguration': False},
            'budget': {'maxItems': mediaset.MAX_ITEMS, 'maxItemBytes': mediaset.ITEM_BYTES, **mediaset.large_bounds(media), 'maxTotalBytes': mediaset.TOTAL_BYTES, 'maxScannedEntries': mediaset.MAX_SCANNED,
                       'maxFolderDepth': mediaset.MAX_DEPTH, 'maxNativeTagsPerFile': listing.MAX_TAGS, 'maxNativeListingBytes': listing.MAX_STDOUT},
            'catalogue': {'version': version, 'sha256': catalogue_digest(version)}, 'losses': LOSSES}


E3_OPERATIONS = ('reconcileTime', 'locate')


def plan_e3(operation, p, media):
    """The plan of an E3 read operation: the operation selects the internal expanded catalogue view, so no author key names a catalogue, overlay or field."""
    block = {'time': e3reports.plan_reconcile(p, media)} if operation == 'reconcileTime' else {'location': e3reports.plan_locate(p)}
    return {'version': PLAN_VERSION, 'operation': operation, 'media': media, 'profiles': [], 'fields': e3read.field_names(operation), 'nativeListing': False, 'audit': None, 'compare': None, **block,
            'settings': {'nativeArguments': listing.FIXED, 'threads': 1, 'userConfiguration': False},
            'budget': {'maxItems': mediaset.MAX_ITEMS, 'maxItemBytes': mediaset.ITEM_BYTES, **mediaset.large_bounds(media), 'maxTotalBytes': mediaset.TOTAL_BYTES, 'maxScannedEntries': mediaset.MAX_SCANNED,
                       'maxFolderDepth': mediaset.MAX_DEPTH, 'maxNativeTagsPerFile': listing.MAX_TAGS, 'maxNativeListingBytes': listing.MAX_STDOUT},
            'catalogue': {'version': catalogue.VERSION_E3, 'sha256': catalogue_digest(catalogue.VERSION_E3)}, 'losses': LOSSES + (e3reports.TIME_LOSSES if operation == 'reconcileTime' else e3reports.LOCATION_LOSSES)}


def schema():
    from schemaxis.schema import DRAFT, argument_schema, object_schema

    def branch(operation, required):
        return object_schema({'version': {'const': VERSION}, 'operation': {'const': operation}, **{k: argument_schema(v) for k, v in OPTIONS[operation].items()}},
                             ['version', 'operation', *required])
    branches = [branch('inspectMetadata', ['media', 'profiles']), branch('auditMetadata', ['media']), branch('compareMetadata', ['media', 'baseline']), branch('reconcileTime', ['media']), branch('locate', ['media'])]
    properties = {'version': {'const': VERSION}, 'operation': {'enum': list(OPERATIONS)}, **{k: argument_schema(v) for options in OPTIONS.values() for k, v in options.items()}}
    return {'$schema': DRAFT, **object_schema(properties, ['version', 'operation']), 'oneOf': branches}


def resources(document, execution, identity):
    if execution.get('threads', 1) != 1:
        fail('INVALID_EXECUTION', 'metadata work runs one serial native thread', identity)
    return {'threads': 1}


def plan_hash(p): return legacy.plan_hash(p)


def reusableInputs(document):
    """Bound input provenance: every included source and sidecar by digest, plus a folder manifest digest so an added or removed file invalidates reuse."""
    p = plan(document)
    found = {}
    for target in collect(p)[1]:
        for entry in [target, target.get('sidecar')]:
            if entry is not None:
                found[entry['path']] = hashlib.sha256(mediaset.read_file(entry['path'], entry.get('identity'), mediaset.item_limit(entry['path']), '$.media')).hexdigest()
    if p['media']['kind'] == 'folder':
        rows, _, _ = mediaset.expand(p['media'])
        found[p['media']['folder']['path']] = mediaset.manifest_digest(rows)
    return found


# ---------------------------------------------------------------- bounded evidence helpers
def fault_dict(code, message, location='$', **observed):
    return Fault(code, message, location, 'pipeline', observed=observed).to_dict()


def read_json(directory, name): return legacy.strict_json(legacy.bounded(directory / name, limit=JSON_LIMIT), name)
def file_digest(directory, name, limit=JSON_LIMIT): return legacy.sha(legacy.bounded(directory / name, limit=limit))
def evidence_limit(name): return mediaset.item_limit(name) if name.startswith(CAPTURED + '/') else JSON_LIMIT
def encode(value): return legacy.encode_json(value)


# ---------------------------------------------------------------- collection and capture
def collect(p):
    """``(rows, targets, signature)``: the pre-capture manifest rows, items to capture and the folder change signature."""
    media = p['media']
    if media['kind'] == 'folder':
        rows, found, signature = mediaset.expand(media)
        targets = []
        for index, f in enumerate(found):
            entry = f['entry']
            side = f['sidecar']
            targets.append({'id': f['id'], 'path': entry['abs'], 'rel': entry['path'], 'identity': entry['identity'],
                            'sidecar': None if side is None else {'path': side['abs'], 'rel': side['path'], 'identity': side['identity']}})
        return rows, targets, signature
    rows, targets = [], []
    for index, item in enumerate(media['items']):
        rows.append({'path': Path(item['path']).name, 'role': 'item', 'included': True, 'id': item['id']})
        if 'sidecar' in item:
            rows.append({'path': Path(item['sidecar']).name, 'role': 'sidecar', 'included': True, 'reason': 'sidecar-of:' + item['id'], 'id': item['id']})
        targets.append({'id': item['id'], 'path': item['path'], 'rel': Path(item['path']).name, 'identity': None, 'pin': item.get('sha256'), 'index': index,
                        'sidecar': {'path': item['sidecar'], 'rel': Path(item['sidecar']).name, 'identity': None} if 'sidecar' in item else None})
    return rows, targets, None


def captured_name(target, data_kind, suffix):
    return '%s/%s%s' % (CAPTURED, target['id'], '.sidecar.xmp' if data_kind == 'sidecar' else suffix)


def capture_target(p, order, target, seen, running):
    """Admit one item: ``(entry, files)`` where a fault leaves ``files`` empty. Only schemaxis faults become item faults."""
    entry = {'id': target['id'], 'order': order, 'source': target['path'], 'relative': target['rel'], 'file': None, 'sha256': None, 'bytes': None, 'container': None, 'sidecar': None, 'fault': None}
    at = '$.media.items[%d].path' % target['index'] if 'index' in target else target['rel']
    files = {}
    try:
        identity = target['identity'] or mediaset.explicit_stat(target['path'], at, target['id'])
        if identity in seen:
            fail('DUPLICATE_PHOTO_SOURCE', 'two items reach the same file (alias, link or hard link); select each source file once', at, photo=target['id'], firstPhoto=seen[identity], expected='distinct source file', observed='same device and inode')
        data = mediaset.read_file(target['path'], identity, mediaset.item_limit(target['path']), at, photo=target['id'])
        seen[identity] = target['id']
        entry.update(sha256=mediaset.sha(data), bytes=len(data))
        if target.get('pin') and target['pin'] != entry['sha256']:
            fail('PHOTO_HASH_MISMATCH', 'item bytes differ from the pinned sha256', at.replace('.path', '.sha256'), photo=target['id'], observed=entry['sha256'])
        try:
            located = e5locate.locate(data, target['rel'])
        except containers.Refused as error:
            fail(error.code, error.message, at, photo=target['id'], **error.observed)
        suffix = e5profiles.extension(located) or Path(target['path']).suffix.lower()
        entry.update(container=located['container'], file=captured_name(target, 'item', suffix))
        files[entry['file']] = data
        side = target['sidecar']
        if side is not None:
            side_at = at.replace('.path', '.sidecar') if 'index' in target else side['rel']
            side_identity = side['identity'] or mediaset.explicit_stat(side['path'], side_at, target['id'])
            if side_identity in seen or side_identity == identity:
                fail('DUPLICATE_PHOTO_SOURCE', 'the sidecar reaches a file that is already an item or sidecar', side_at, photo=target['id'])
            side_data = mediaset.read_file(side['path'], side_identity, mediaset.ITEM_BYTES, side_at, photo=target['id'])
            try:
                side_located = containers.locate(side_data)
            except containers.Refused as error:
                fail('INVALID_SIDECAR', 'the sidecar cannot be read as an XMP packet: ' + error.message, side_at, photo=target['id'], cause=error.code)
            if side_located['container'] != 'xmp':
                fail('INVALID_SIDECAR', 'the sidecar is not an XMP packet', side_at, photo=target['id'])
            seen[side_identity] = target['id']
            entry['sidecar'] = {'source': side['path'], 'relative': side['rel'], 'file': captured_name(target, 'sidecar', ''), 'sha256': mediaset.sha(side_data), 'bytes': len(side_data)}
            files[entry['sidecar']['file']] = side_data
        running[0] += sum(len(v) for v in files.values())
        if running[0] > mediaset.TOTAL_BYTES:
            fail('MEDIA_RESOURCE_LIMIT', 'captured items exceed %d bytes in total; select fewer or smaller items' % mediaset.TOTAL_BYTES, at, photo=target['id'], observed=running[0])
    except SchemaxisError as error:
        if error.fault.code == 'MEDIA_RESOURCE_LIMIT':
            raise
        entry.update(fault=error.fault.to_dict())
        return entry, {}
    return entry, files


def source_set(p, rows, signature):
    media = p['media']
    return {'kind': media['kind'], **({'folder': {k: v for k, v in media['folder'].items() if k != 'path'}} if media['kind'] == 'folder' else {'items': len(media['items'])})}


def native_names(items):
    return [name for i in items if i['status'] == 'ok' for name in [i['file'], *([i['sidecar']['file']] if i['sidecar'] else [])]]


# ---------------------------------------------------------------- admission from retained bytes (shared by run and verify)
def admit(directory, p, captured):
    items = []
    for entry in captured['items']:
        item = {**entry, 'status': 'fault' if entry['fault'] else 'ok', 'fields': None, 'native': None, 'notes': [], 'frame': None}
        if entry['fault'] is None:
            data = legacy.bounded(directory / entry['file'], limit=mediaset.item_limit(entry['file']))
            if legacy.sha(data) != entry['sha256'] or len(data) != entry['bytes']:
                fail('VERIFICATION_FAILED', 'a retained captured item differs from its capture record', entry['file'])
            side = None
            if entry['sidecar']:
                side_data = legacy.bounded(directory / entry['sidecar']['file'], limit=mediaset.ITEM_BYTES)
                if legacy.sha(side_data) != entry['sidecar']['sha256'] or len(side_data) != entry['sidecar']['bytes']:
                    fail('VERIFICATION_FAILED', 'a retained captured sidecar differs from its capture record', entry['sidecar']['file'])
                side = locate(side_data, entry['sidecar']['file'])
            located = locate(data, entry['file'], entry.get('relative'))
            if located['container'] != entry['container']:
                fail('VERIFICATION_FAILED', 'the retained item container differs from its capture record', entry['file'])
            _, fields, payloads = records.build(located, p['fields'], side, plan_catalogue(p))
            item.update(fields=fields, notes=payloads.notes, frame=located['frame'], payloads=payloads)
        items.append(item)
    return items


def locate(data, name, source=None):
    try:
        return e5locate.locate(data, source) if source is not None else e5locate.locate(data)
    except containers.Refused as error:
        fail('VERIFICATION_FAILED', 'a retained captured file cannot be located again: ' + error.message, name)


def apply_native(p, items, stdout):
    """Parse the retained native listing and anchor every ok item; items that fail anchoring become faults. Returns the parsed per-file records."""
    names = native_names(items)
    try:
        parsed = listing.parse(stdout, names) if names else []
    except (ValueError, UnicodeDecodeError, RecursionError) as error:
        fail('NATIVE_OBSERVATION_MISMATCH', 'the native listing is not the strict bounded listing of the captured files: ' + str(error)[:200], 'listing')
    by_name = dict(zip(names, parsed))
    for item in items:
        if item['status'] != 'ok':
            continue
        image = by_name[item['file']]
        side = by_name[item['sidecar']['file']] if item['sidecar'] else None
        problems = [r for r in (image, side) if r is not None]
        bound = next((r['fault'] for r in problems if r['fault']), None)
        errors = [e for r in problems for e in r['errors']]
        if bound or errors:
            item.update(status='fault', fields=None, fault=fault_dict(bound['code'] if bound else 'NATIVE_REPORTED_PROBLEM', bound['message'] if bound else 'ExifTool reported an error for a captured file', item['file'],
                                                                      **({} if bound else {'errors': [e[:200] for e in errors[:5]]})))
            continue
        checked, mismatches = listing.anchors(item, item['fields'], {'image': listing.index(image), 'sidecar': listing.index(side) if side else None})
        if mismatches:
            item.update(status='fault', fields=None, fault=fault_dict('NATIVE_ANCHOR_MISMATCH', 'ExifTool and the independent reader disagree about this file, so none of its values is published',
                                                                      item['file'], count=len(mismatches), mismatches=mismatches[:listing.ANCHOR_REPORT]))
            continue
        item['native'] = {'anchorsChecked': checked, 'warnings': [w for r in problems for w in r['warnings']], 'records': {'image': image, 'sidecar': side}}
    return by_name


# ---------------------------------------------------------------- publications
def tabular_text(value):
    """Exact text a typed table can carry, or ``None`` (empty, control characters, workbook-unsafe, too long or the null token)."""
    if not isinstance(value, str) or not value or value == NULL_TOKEN or len(value) > MAX_TEXT:
        return None
    for c in value:
        code = ord(c)
        if code < 32 or 0x7F <= code <= 0x9F or code in (0x2028, 0x2029) or 0xD800 <= code <= 0xDFFF or code in (0xFFFE, 0xFFFF):
            return None
    return value


def csv_bytes(columns, table):
    def cell(value):
        if value is None:
            return NULL_TOKEN
        if isinstance(value, str):
            return '"' + value.replace('"', '""') + '"'
        return json.dumps(value)
    lines = [','.join('"' + name + '"' for name, _, _ in columns)]
    lines += [','.join(cell(v) for v in row) for row in table]
    return ('\n'.join(lines) + '\n').encode('utf-8')


NUMBER_TYPES = ('integer', 'rational', 'code', 'degrees', 'meters')


def profile_table(p, items, profile):
    names = [f for f in catalogue.profile_fields([profile]) if f in p['fields']]
    columns = [('id', 'text', False)]
    for name in names:
        columns += [(name, 'number' if catalogue.fields()[name]['type'] in NUMBER_TYPES else 'text', True), (name + 'State', 'text', False)]
    table = []
    for item in items:
        if item['status'] != 'ok':
            continue
        row = [item['id']]
        for name in names:
            published = records.publish(item['fields'][name])
            value, state = published['value'], published['state']
            if value is not None and catalogue.fields()[name]['type'] not in NUMBER_TYPES:
                value = json.dumps(value, ensure_ascii=False) if isinstance(value, list) else value
                text = tabular_text(value)
                value, state = text, (state if text is not None else 'present-not-tabular')
            row += [value, state]
        table.append(row)
    return columns, table


def item_document(p, item):
    doc = {'id': item['id'], 'order': item['order'], 'status': item['status'], 'source': {'path': item['relative'], 'bytes': item['bytes'], 'sha256': item['sha256'], 'container': item['container']}}
    if item['sidecar']:
        doc['source']['sidecar'] = {'path': item['sidecar']['relative'], 'bytes': item['sidecar']['bytes'], 'sha256': item['sidecar']['sha256']}
    if item['status'] != 'ok':
        doc['fault'] = item['fault']
        return doc
    doc['source']['notes'] = item['notes']
    if item['frame']:
        doc['source']['frame'] = item['frame']
    doc['fields'] = [records.publish(item['fields'][name], plan_catalogue(p) if plan_catalogue(p) == catalogue.VERSION_E3 else catalogue.VERSION) for name in p['fields']]
    doc['native'] = {'anchorsChecked': item['native']['anchorsChecked'], 'warnings': item['native']['warnings']} if item['native'] else None
    return doc


def build_manifest(p, rows, items):
    by_id = {i['id']: i for i in items}
    entries = []
    for row in rows:
        entry = dict(row)
        item = by_id.get(row.get('id'))
        if row['role'] == 'item' and item is not None:
            entry.update(status=item['status'], bytes=item['bytes'], sha256=item['sha256'])
            if item['fault']:
                entry['fault'] = item['fault']
        elif row['role'] == 'sidecar' and item is not None and item['sidecar']:
            entry.update(bytes=item['sidecar']['bytes'], sha256=item['sidecar']['sha256'])
        entries.append(entry)
    ok = sum(1 for i in items if i['status'] == 'ok')
    limited = sum(1 for r in rows if not r['included'] and r.get('reason') in mediaset.LIMIT_REASONS)
    failed = len(items) - ok
    counts = {'scanned': len(rows), 'items': len(items), 'succeeded': ok, 'faulted': failed, 'excluded': sum(1 for r in rows if not r['included']), 'excludedForLimitOrSafety': limited}
    status = 'complete' if not failed and not limited else 'partial'
    return {'version': MANIFEST_VERSION, 'source': source_set(p, rows, None), 'status': status, 'counts': counts, 'entries': entries,
            'statement': 'status is complete only when every included item succeeded and nothing eligible was excluded for a limit or safety reason; otherwise partial'}


def documents(p, rows, items, natives):
    ok = [i for i in items if i['status'] == 'ok']
    manifest = build_manifest(p, rows, items)
    metadata = {'version': METADATA_VERSION, 'operation': p['operation'], 'runtime': RUNTIME, 'catalogue': p['catalogue'],
                'proofLevels': {'independent': 'decoded from the captured bytes by the host reader and anchored against the pinned ExifTool listing',
                                'native-observed': 'ExifTool 13.55 own report for exactly these captured bytes; same-engine replay is reproducibility, not independent confirmation'},
                'assessedFields': p['fields'], 'unassessed': 'every catalogue field not listed in assessedFields, and every tag outside the catalogue, is unassessed: neither read into the records nor claimed absent',
                'setStatus': manifest['status'], 'counts': manifest['counts'], 'items': [item_document(p, i) for i in items], 'review': {'observedMetadataOnly': True, 'captureTimeCertified': False, 'locationOrAuthorshipCertified': False,
                'privacyCertified': False, 'humanReviewRequired': True, 'statement': REVIEW}, 'losses': LOSSES}
    files = {'metadata.json': encode(metadata), 'manifest.json': encode(manifest)}
    tables = {}
    if p['operation'] == 'inspectMetadata':
        for profile in p['profiles']:
            columns, table = profile_table(p, items, profile)
            data = csv_bytes(columns, table)
            files['profile-%s.csv' % profile] = data
            tables[profile] = {'file': 'profile-%s.csv' % profile, 'format': CSV_FORMAT, 'nullToken': NULL_TOKEN, 'columns': [{'name': n, 'kind': k, 'nullable': b} for n, k, b in columns], 'rows': len(table), 'sha256': digest_text(data)}
        if p['nativeListing']:
            files['native-observations.json'] = encode({'version': 'schemaxis.exiftool.native-observations/1', 'runtime': RUNTIME, 'proofLevel': 'native-observed', 'fixedArguments': listing.FIXED,
                'statement': 'ExifTool\'s own listing of the captured files under a fixed argument list. Names and values are observations, never declarations; filesystem/system tags are excluded, warnings are kept and unknown tags are listed. An instance above 0 is another copy of the same name; ambiguous marks a name that appears more than once in one group.',
                'items': [{'id': i['id'], 'files': [{'file': name, 'sha256': digest, **({} if natives is None else {'observations': natives[name]['observations'], 'warnings': natives[name]['warnings']})}
                                                    for name, digest in [(i['file'], i['sha256']), *([(i['sidecar']['file'], i['sidecar']['sha256'])] if i['sidecar'] else [])]]} for i in ok]})
    if p['operation'] == 'auditMetadata':
        findings = auditing.audit(ok, p['audit'])
        summary = {'findings': len(findings), 'bySeverity': {s: sum(1 for f in findings if f['severity'] == s) for s in ('warning', 'info')}, 'byRule': {r: sum(1 for f in findings if f['rule'] == r) for r in p['audit']['rules']},
                   'itemsAudited': len(ok), 'itemsFaulted': len(items) - len(ok)}
        files['audit.json'] = encode({'version': 'schemaxis.exiftool.audit/1', 'rules': p['audit']['rules'], 'require': p['audit']['require'], 'gpsToleranceSeconds': p['audit']['gpsToleranceSeconds'],
                                      'summary': summary, 'findings': findings, 'statement': 'Findings are observations about recorded metadata; a file with no finding is not certified, and a finding is not proof of tampering.'})
        columns = [('item', 'text', False), ('rule', 'text', False), ('severity', 'text', False), ('field', 'text', True), ('status', 'text', False), ('message', 'text', False)]
        files['findings.csv'] = csv_bytes(columns, [[f['item'], f['rule'], f['severity'], f['field'], f['status'], f['message']] for f in findings])
    if p['operation'] == 'reconcileTime':
        files.update(e3reports.time_documents(p, items, encode, csv_bytes, RUNTIME))
    if p['operation'] == 'locate':
        files.update(e3reports.location_documents(p, items, encode, csv_bytes, RUNTIME, lambda item: item['payloads']))
    if p['operation'] == 'compareMetadata':
        baseline = p['compare']['baseline']
        if baseline not in [i['id'] for i in ok]:
            fail('INVALID_BASELINE', 'the baseline item is not a usable item of this set', '$.baseline', value=baseline, usable=[i['id'] for i in ok][:20])
        rows_out = auditing.compare(ok, baseline, p['fields'])
        summary = {'baseline': baseline, 'comparisons': len(rows_out), 'byOutcome': {o: sum(1 for r in rows_out if r['outcome'] == o) for o in auditing.OUTCOMES}, 'itemsCompared': len(ok) - 1, 'itemsFaulted': len(items) - len(ok)}
        files['comparison.json'] = encode({'version': 'schemaxis.exiftool.comparison/1', 'baseline': baseline, 'fields': p['fields'], 'summary': summary, 'rows': rows_out,
                                           'statement': 'Outcomes compare canonical recorded values literally; different is not wrong, and same is not authentic.'})
        columns = [('item', 'text', False), ('field', 'text', False), ('outcome', 'text', False), ('baselineState', 'text', False), ('itemState', 'text', False), ('baselineValue', 'text', True), ('itemValue', 'text', True)]
        def text(value): return None if value is None else tabular_text(json.dumps(value, ensure_ascii=False) if not isinstance(value, str) else value)
        files['differences.csv'] = csv_bytes(columns, [[r['item'], r['field'], r['outcome'], r['baseline']['state'], r['other']['state'], text(r['baseline']['value']), text(r['other']['value'])] for r in rows_out])
    return files, tables


def published_names(p):
    names = ['metadata.json', 'manifest.json']
    if p['operation'] == 'inspectMetadata':
        names += ['profile-%s.csv' % x for x in p['profiles']] + (['native-observations.json'] if p['nativeListing'] else [])
    elif p['operation'] == 'auditMetadata':
        names += ['audit.json', 'findings.csv']
    elif p['operation'] == 'reconcileTime':
        names += ['time-report.json', 'time-report.csv']
    elif p['operation'] == 'locate':
        names += ['location-report.json', 'location.csv']
    else:
        names += ['comparison.json', 'differences.csv']
    return names


def artifacts(directory, p):
    out = []
    for name in published_names(p):
        record = {'file': str(directory / name), 'kind': 'table' if name.endswith('.csv') else 'text', 'sha256': file_digest(directory, name)}
        if name.endswith('.csv'):
            record.update(identity={'kind': 'table', 'format': CSV_FORMAT, 'nullToken': NULL_TOKEN}, losses=LOSSES,
                          verificationScope='Typed rows rebuilt from an independent reader over the captured bytes and anchored against ExifTool; null means no published value (the State column says why). Not a general CSV validator or capture-truth check.')
        out.append(record)
    return out


# ---------------------------------------------------------------- native stages
def commands(script, names):
    lib = str(Path(script).parent / 'lib')
    listing_command = [PERL, script, *listing.FIXED, *names]
    return {'version': [PERL, script, '-config', '', '-ver'], 'libraries': [PERL, '-e', '1'], 'modules': [PERL, '-I', lib, '-e', legacy.MODULE_PROBE],
            'listing': listing_command, 'repeat': list(listing_command)}


def stage_names(stage, names): return list(names) if stage in ('listing', 'repeat') else []


def bound_of(names):
    """The largest item bound of the inputs a launcher names (64 MiB unless a TIFF or DNG is among them)."""
    return max([mediaset.item_limit(n) for n in names] + [mediaset.ITEM_BYTES])


def fsize_of(names):
    """The file-size limit of the native process: unchanged for ordinary inputs, twice the item bound when a TIFF or DNG (256 MiB) is among them."""
    return 2 * listing.MAX_STDOUT if bound_of(names) == mediaset.ITEM_BYTES else 2 * bound_of(names)


def launcher(stage, command, names):
    environment = {'LANG': 'C', 'LC_ALL': 'C', **({'LD_TRACE_LOADED_OBJECTS': '1'} if stage == 'libraries' else {})}
    return ('import hashlib,json,os,resource,stat\nfrom pathlib import Path\n'
            + 'command=%r\nnames=%r\nenvironment=%r\nbindings={"files":{}}\n' % (command, stage_names(stage, names), environment)
            + 'resource.setrlimit(resource.RLIMIT_CPU,(600,600))\nresource.setrlimit(resource.RLIMIT_FSIZE,(%d,%d))\nresource.setrlimit(resource.RLIMIT_AS,(4294967296,4294967296))\nresource.setrlimit(resource.RLIMIT_CORE,(0,0))\n' % (fsize_of(stage_names(stage, names)), fsize_of(stage_names(stage, names)))
            + 'for name in names:\n    fd=os.open(name,os.O_RDONLY|os.O_NOFOLLOW|getattr(os,"O_NONBLOCK",0))\n'
            + '    with os.fdopen(fd,"rb") as stream:\n        info=os.fstat(stream.fileno())\n'
            + '        if not stat.S_ISREG(info.st_mode) or info.st_size>%d: raise ValueError("invalid native input")\n' % bound_of(stage_names(stage, names))
            + '        h=hashlib.sha256();count=0\n        for block in iter(lambda:stream.read(1<<20),b""):\n            count+=len(block);h.update(block)\n'
            + '        if count!=info.st_size: raise ValueError("native input changed while read")\n    bindings["files"][name]=h.hexdigest()\n'
            + 'Path(%r).write_text(json.dumps(bindings,sort_keys=True))\n' % (stage + '-inputs.json')
            + 'os.execve(command[0],command,dict(environment))\n')


def run_stage(directory, stage, command, names, timeout):
    path = directory / (stage + '-launcher.py')
    path.write_text(launcher(stage, command, names))
    return execute([sys.executable, str(path)], directory, stage, timeout, {'LANG': 'C.UTF-8'})


def retained_names(captured, native_files):
    names = {'authored.json', 'plan.json', 'captures.json', 'runtime.json'}
    for entry in captured['items']:
        if entry['fault'] is None:
            names.add(entry['file'])
            if entry['sidecar']:
                names.add(entry['sidecar']['file'])
    for stage in STAGES:
        names |= {stage + x for x in ('-launcher.py', '-inputs.json', '-submission.json', '.stdout', '.stderr')}
    return names


def membership(directory, p, captured):
    from schemaxis.run_paths import MANIFEST
    expected = {n for n in retained_names(captured, None) if '/' not in n} | set(published_names(p)) | {'verification.json', 'result.json', 'schema.snapshot.json', MANIFEST, 'job.json'}
    expected |= {name + '.metadata.json' for name in published_names(p)}
    for path in directory.iterdir():
        if path.name in ('.dispatch', CAPTURED):
            if path.is_symlink() or not path.is_dir():
                fail('VERIFICATION_FAILED', 'owned member is not a directory', path.name)
        elif path.name not in expected or path.is_symlink() or not path.is_file():
            fail('VERIFICATION_FAILED', 'unexpected or nonregular retained member', path.name)
    wanted = sorted(Path(n).name for n in retained_names(captured, None) if n.startswith(CAPTURED + '/'))
    present = sorted(x.name for x in (directory / CAPTURED).iterdir()) if (directory / CAPTURED).is_dir() else []
    if present != wanted:
        fail('VERIFICATION_FAILED', 'retained captured-file membership differs', CAPTURED)
    for x in (directory / CAPTURED).iterdir():
        if x.is_symlink() or not x.is_file():
            fail('VERIFICATION_FAILED', 'a retained captured file is not a regular file', CAPTURED + '/' + x.name)


# ---------------------------------------------------------------- run
def run(document, directory, *, executable=None, timeout=300):
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

    def checkpoint():
        if cancellation_requested():
            fail('RUNNER_CANCELLED', 'metadata work cancelled')
        remaining_timeout(timeout)
    try:
        with execution_deadline(timeout):
            checkpoint()
            rows, targets, signature = collect(p)
            (directory / CAPTURED).mkdir()
            seen, running, items, written = {}, [0], [], {}
            for order, target in enumerate(targets, 1):
                checkpoint()
                entry, files = capture_target(p, order, target, seen, running)
                for name, data in files.items():
                    (directory / name).write_bytes(data)
                items.append(entry)
            if signature is not None:
                _, _, after = collect_signature(p)
                if after != signature:
                    fail('MEDIA_FOLDER_CHANGED', 'the media folder changed while its items were captured; run again when it is stable', '$.media.folder.path',
                         changed=sorted({k for k in set(signature) | set(after) if signature.get(k) != after.get(k)})[:20])
            captured = {'source': source_set(p, rows, signature), 'rows': rows, 'items': items}
            atomic_json(directory / 'captures.json', captured)
            admitted = admit(directory, p, captured)
            usable = [i for i in admitted if i['status'] == 'ok']
            if not usable:
                files, _ = documents_failure(p, rows, admitted)
                (directory / 'manifest.json').write_bytes(files)
                fail('NO_USABLE_ITEMS', 'no item of the media set could be admitted; manifest.json lists every item and its fault', '$.media', items=len(admitted), firstFaults=[i['fault'] for i in admitted[:3]])
            names = native_names(admitted)
            runtime = None
            for stage, command in commands(executable, names).items():
                checkpoint()
                run_stage(directory, stage, command, names, remaining_timeout(timeout))
                if stage == 'version':
                    legacy.qualified_runtime(directory)
                if stage == 'modules':
                    runtime = legacy.runtime_identity(directory, executable, checkpoint)
            checkpoint()
            if legacy.runtime_identity(directory, executable, checkpoint) != runtime:
                fail('RUNTIME_CHANGED', 'ExifTool, Perl or a dependency changed during the run')
            for entry in usable:
                if legacy.stream_capture(entry['source'], mediaset.item_limit(entry['source']), 'PHOTO_CHANGED', location='$.media')['sha256'] != entry['sha256']:
                    fail('PHOTO_CHANGED', 'a source item changed during the native run', '$.media', photo=entry['id'])
            atomic_json(directory / 'runtime.json', {'executable': executable, **runtime})
            first, second = legacy.bounded(directory / 'listing.stdout', limit=listing.MAX_STDOUT + 1), legacy.bounded(directory / 'repeat.stdout', limit=listing.MAX_STDOUT + 1)
            if legacy.bounded(directory / 'listing.stderr', limit=legacy.LOG_LIMIT) or first != second:
                fail('NATIVE_OBSERVATION_MISMATCH', 'the second fresh ExifTool process did not repeat the first byte for byte, or the first wrote to stderr', 'repeat')
            natives = apply_native(p, admitted, first)
            if not any(i['status'] == 'ok' for i in admitted):
                files, _ = documents_failure(p, rows, admitted)
                (directory / 'manifest.json').write_bytes(files)
                fail('NO_USABLE_ITEMS', 'every item was refused after the native cross-check; manifest.json lists every item and its fault', '$.media', items=len(admitted), firstFaults=[i['fault'] for i in admitted[:3]])
            files, _ = documents(p, rows, admitted, {n: r for n, r in natives.items()})
            for name, data in files.items():
                (directory / name).write_bytes(data)
            atomic_json(directory / 'verification.json', {'executable': executable, 'runtime': RUNTIME, 'planSha256': plan_hash(p), 'artifacts': artifacts(directory, p),
                                                          'evidence': {n: file_digest(directory, n, evidence_limit(n)) for n in sorted(retained_names(captured, None))}})
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


def collect_signature(p):
    return mediaset.expand(p['media'])


def documents_failure(p, rows, items):
    return encode(build_manifest(p, rows, items)), None


# ---------------------------------------------------------------- verification
def trusted_runtime(executable):
    value = executable or configured_executable('exiftool') or os.environ.get('SCHEMAXIS_EXIFTOOL')
    if isinstance(value, str) and os.path.isabs(value) and os.path.isfile(value) and os.access(value, os.R_OK):
        return value
    return None


def replay(directory, p, names, executable, retained):
    """Fresh native listing of the retained captured bytes with the trusted runtime, compared with the retained listing.

    ``names`` are the files the retained listing was made over: every admitted capture, fixed before the native cross-check refuses any item.
    A file whose item was later refused is still in that listing, so the replay must list it too.
    """
    scratch = Path(tempfile.mkdtemp(prefix='schemaxis-exiftool-'))
    try:
        (scratch / CAPTURED).mkdir()
        for name in names:
            (scratch / name).write_bytes(legacy.bounded(directory / name, limit=mediaset.item_limit(name)))
        for stage in ('version', 'listing'):
            command = commands(executable, names)[stage]
            run_stage(scratch, stage, command, names, remaining_timeout(VERIFY_TIMEOUT))
            if stage == 'version':
                text = legacy.bounded(scratch / 'version.stdout', 'NATIVE_REPLAY_UNAVAILABLE', 4096).decode('utf-8', 'replace')
                if text != '13.55\n':
                    fail('NATIVE_REPLAY_UNAVAILABLE', 'the configured ExifTool is not the pinned 13.55 production release', 'version', observed=text[:80], independentVerified=True)
        fresh = legacy.bounded(scratch / 'listing.stdout', limit=listing.MAX_STDOUT + 1)
        if legacy.bounded(scratch / 'listing.stderr', limit=legacy.LOG_LIMIT):
            fail('VERIFICATION_FAILED', 'the fresh native replay wrote to stderr', 'listing')
        if fresh != retained:
            fail('VERIFICATION_FAILED', 'the fresh native replay of the retained captured bytes differs from the retained listing', 'listing')
        return legacy.sha(fresh)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


def verify(directory, require_result=True, *, executable=None):
    """Re-derive independent values from the retained bytes, rebuild every publication, and replay the native listing with the trusted runtime.

    A native listing that cannot be replayed (no configured trusted runtime) is reported as NATIVE_REPLAY_UNAVAILABLE and is never verified.
    Receipt executables are inert provenance and are never launched; PATH is not consulted.
    """
    directory = Path(directory).absolute()
    try:
        with execution_deadline(VERIFY_TIMEOUT):
            p = plan(legacy.read(directory, 'authored.json'))
            receipt = read_json(directory, 'verification.json')
            if not isinstance(receipt, dict) or set(receipt) != {'executable', 'runtime', 'planSha256', 'artifacts', 'evidence'} or not isinstance(receipt['evidence'], dict):
                fail('VERIFICATION_FAILED', 'native receipt member set differs')
            if not legacy.same_json(read_json(directory, 'plan.json'), p) or receipt['planSha256'] != plan_hash(p):
                fail('VERIFICATION_FAILED', 'effective plan differs from the authored input or receipt')
            if require_result and read_json(directory, 'result.json').get('status') != 'succeeded':
                fail('INCOMPLETE_EXECUTION', 'metadata work did not complete')
            captured = read_json(directory, 'captures.json')
            if not isinstance(captured, dict) or set(captured) != {'source', 'rows', 'items'} or not isinstance(captured['items'], list) or not isinstance(captured['rows'], list):
                fail('VERIFICATION_FAILED', 'capture record member set differs')
            membership(directory, p, captured)
            items = admit(directory, p, captured)
            listing_bytes = legacy.bounded(directory / 'listing.stdout', limit=listing.MAX_STDOUT + 1)
            if legacy.bounded(directory / 'listing.stderr', limit=legacy.LOG_LIMIT) or listing_bytes != legacy.bounded(directory / 'repeat.stdout', limit=listing.MAX_STDOUT + 1):
                fail('VERIFICATION_FAILED', 'the repeated fresh process differs from the first, or the first wrote to stderr', 'repeat')
            names = tuple(native_names(items))     # every admitted capture: the files the retained listing covers, before anchoring refuses any item
            retained_executable = receipt['executable']
            if not isinstance(retained_executable, str) or not Path(retained_executable).is_absolute():
                fail('VERIFICATION_FAILED', 'native executable identity must be absolute')
            for stage, command in commands(retained_executable, names).items():
                submission = read_json(directory, stage + '-submission.json')
                path = directory / (stage + '-launcher.py')
                interpreter = submission.get('interpreter', {}).get('executable') if isinstance(submission, dict) and isinstance(submission.get('interpreter'), dict) else None
                if not isinstance(interpreter, str) or not Path(interpreter).is_absolute() or submission.get('nativeCommand') != [interpreter, str(path)] or type(submission.get('exitCode')) is not int or submission['exitCode'] != 0:
                    fail('VERIFICATION_FAILED', 'native command/completion differs', stage)
                if legacy.bounded(path).decode() != launcher(stage, command, names):
                    fail('VERIFICATION_FAILED', 'trusted native launcher differs', stage)
                expected = {'files': {n: file_digest(directory, n, evidence_limit(n)) for n in stage_names(stage, names)}}
                if not legacy.same_json(read_json(directory, stage + '-inputs.json'), expected):
                    fail('VERIFICATION_FAILED', 'native input binding differs', stage)
            if receipt['runtime'] != legacy.qualified_runtime(directory, 'VERIFICATION_FAILED'):
                fail('VERIFICATION_FAILED', 'require qualified ExifTool 13.55 runtime identity')
            check_runtime_record(directory, retained_executable)
            natives = apply_native(p, items, listing_bytes)
            files, tables = documents(p, captured['rows'], items, natives)
            for name, content in files.items():
                if legacy.bounded(directory / name, limit=JSON_LIMIT) != content:
                    fail('VERIFICATION_FAILED', 'published file differs from independently derived evidence', name)
            if not legacy.same_json(receipt['artifacts'], artifacts(directory, p)):
                fail('VERIFICATION_FAILED', 'publication membership/digest differs')
            if set(receipt['evidence']) != retained_names(captured, None):
                fail('VERIFICATION_FAILED', 'native evidence membership differs')
            for n in retained_names(captured, None):
                if file_digest(directory, n, evidence_limit(n)) != receipt['evidence'][n]:
                    fail('VERIFICATION_FAILED', 'retained native evidence differs', n)
            ok = [i for i in items if i['status'] == 'ok']
            trusted = trusted_runtime(executable)
            replay_digest = None
            if trusted is not None:
                replay_digest = replay(directory, p, names, trusted, listing_bytes)
            elif p['nativeListing']:
                fail('NATIVE_REPLAY_UNAVAILABLE', 'native-observed values cannot be verified without a configured trusted ExifTool 13.55 runtime to replay them; independent values re-derived from the retained bytes are consistent but the native listing is not verified', '$.runtime.exiftool',
                     independentVerified=True, nativeVerified=False, recovery='use --exiftool, schemaxis configure exiftool, or SCHEMAXIS_EXIFTOOL (a receipt executable is never launched)')
            manifest = json.loads(files['manifest.json'])
            fresh = {'verified': True, 'artifacts': len(files), 'runtime': RUNTIME, 'operation': p['operation'], 'items': len(items), 'succeeded': len(ok), 'faulted': len(items) - len(ok),
                     'setStatus': manifest['status'], 'manifestSha256': legacy.sha(files['manifest.json']), 'publicationSha256': {n: legacy.sha(c) for n, c in sorted(files.items())},
                     'nativeListing': p['nativeListing'], 'nativeReplay': 'fresh-replay-matched' if replay_digest else 'not-replayed (no trusted runtime configured; no native-observed value is published)',
                     'proofLevels': ['independent'] + (['native-observed'] if p['nativeListing'] else []), 'observedMetadataOnly': True, 'captureTimeCertified': False, 'humanReviewRequired': True}
            retained = read_json(directory, 'result.json') if require_result else None
            if require_result and not legacy.same_json({k: v for k, v in retained.items() if k != 'nativeReplay'}, {**{k: v for k, v in fresh.items() if k != 'nativeReplay'}, 'status': 'succeeded'}):
                fail('VERIFICATION_FAILED', 'retained result differs from independent reopening')
            return fresh
    except SchemaxisError as error:
        if error.fault.code in ('VERIFICATION_FAILED', 'INCOMPLETE_EXECUTION', 'NATIVE_REPLAY_UNAVAILABLE', 'RUNNER_CANCELLED', 'RUNNER_TIMED_OUT'):
            raise
        fail('VERIFICATION_FAILED', 'retained evidence violates its contract (' + error.fault.code + ': ' + error.fault.message + ')', error.fault.location, cause=error.fault.to_dict())
    except (OSError, ValueError, KeyError, TypeError, IndexError, AttributeError, UnicodeDecodeError, RecursionError) as error:
        fail('VERIFICATION_FAILED', 'invalid retained evidence: ' + str(error))


def check_runtime_record(directory, executable):
    runtime = read_json(directory, 'runtime.json')
    if not isinstance(runtime, dict) or set(runtime) != {'executable', 'files', 'library'} or runtime['executable'] != executable or not isinstance(runtime['files'], list) or not isinstance(runtime['library'], dict):
        fail('VERIFICATION_FAILED', 'runtime identity member set differs')
    wanted = [('perl', PERL), ('exiftool', executable), *legacy.loader_paths(directory), *legacy.module_paths(directory)]
    if [(f.get('name'), f.get('path')) for f in runtime['files'] if isinstance(f, dict)] != wanted or len(runtime['files']) != len(wanted):
        fail('VERIFICATION_FAILED', 'runtime dependency identity differs from the loader and module traces')
    library = runtime['library']
    if set(library) != {'files', 'bytes', 'manifestSha256', 'members'} or not isinstance(library['members'], list) or not library['members'] or library['files'] != len(library['members']) or library['manifestSha256'] != legacy.sha(legacy.encode_json(library['members'])):
        fail('VERIFICATION_FAILED', 'ExifTool library manifest is malformed')
    if not all(isinstance(f, dict) and set(f) >= {'name', 'sha256', 'bytes'} and isinstance(f['sha256'], str) and legacy.HEX.fullmatch(f['sha256']) and legacy.whole(f['bytes']) and 0 <= f['bytes'] <= legacy.RUNTIME_FILE_LIMIT for f in [*runtime['files'], *library['members']]) or library['bytes'] != sum(f['bytes'] for f in library['members']):
        fail('VERIFICATION_FAILED', 'runtime file hashes are malformed')
