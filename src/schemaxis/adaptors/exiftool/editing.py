"""Metadata write family: editMetadata and removeMetadata over captured JPEG copies of a bounded media set.

Every original is captured byte for byte into the run and is never written, renamed or linked. Each item is planned from its capture by the
independent readers, written by one genuine ExifTool 13.55 process (its own process group) into a private stage, and published into the run
only when three independent proofs hold on the written bytes:

* R, readback: every requested value or absence is read back out of the output with the standard-library readers (type, encoding, list
  shape, language set, source concordance), and untouched IPTC meaning is unchanged;
* P, preservation: the encoded image (frame header, coding tables, every entropy-coded scan, restart markers, end marker) and the rendering
  segments are byte-identical, and only declared metadata segments differ. Nothing here decodes pixels or says anything about authenticity;
* N, native diff: fresh ExifTool listings of capture and output differ only at the plan's targets and in a closed set of value-aware side effects.

A refused or failed item never blocks the others. The receipt lists one artifact slot per item in manifest order (the published JPEG, or the
truthful outcome document of a refused item, which is never an image) before the report documents, so a consumer index can never silently
select another item's picture. Verification recomputes every proof from the retained bytes and replays the native listings and the writes
with a trusted runtime.
"""
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile

from schemaxis.adaptors.exiftool import adaptor as legacy, catalogue, containers, e3docs, e5edit, e5proof, e3proofs, e3write, e3writes, e4copy, edits, jpegwrite, listing, mediaset, options, proofs, records, removal, workbench as wb, writes, xmp as xmp_reader
from schemaxis.artifacts import atomic_json
from schemaxis.core.declarations import validate_arguments
from schemaxis.core.faults import SchemaxisError
from schemaxis.dispatch import cancellation_requested, execution_deadline, remaining_timeout
from schemaxis.errors import fail, keys
from schemaxis.native_command import execute

OPERATIONS = tuple(options.WRITE_OPTIONS)
VERSION = legacy.VERSION
PLAN_VERSION = 'schemaxis.exiftool.edit.plan/1'
REPORT_VERSION = 'schemaxis.exiftool.edit.report/1'
RUNTIME, PERL = legacy.RUNTIME, legacy.PERL
STATIC_STAGES = ('version', 'libraries', 'modules', 'before', 'after')
CAPTURED, STAGE, PHOTOS, OUTCOMES, REJECTED = 'captured', 'stage', 'photos', 'outcomes', 'rejected'
JSON_LIMIT = wb.JSON_LIMIT
LOSSES = [
    'Scope: JPEG files only (baseline, extended sequential and progressive Huffman, any number of scans). Trailing bytes, extended XMP, MPF, FlashPix, segments after the first scan other than DHT/DQT/DRI/SOS, restart sequences that do not cycle, damaged Exif or XMP or IPTC, native warnings and sidecar pairs are refused per item with a stable code; the capture is still reported.',
    'Proof P is a statement about bytes: the frame header, coding tables, every entropy-coded scan, restart marker and the end marker are byte-identical to the capture, and JFIF, Adobe and ICC segments are unchanged. No decoder is run: this says nothing about pixels, rendering in any program, authenticity, provenance or C2PA.',
    'Proof R covers the catalogued target fields only. Text is exact and never normalised: NFC and NFD stay distinct, and the language tag case ExifTool normalises (fr-ca becomes fr-CA) is reported, not hidden.',
    'Proof N compares two fresh ExifTool listings of the same engine that wrote the file. That is reproducibility, not independent truth: it can reveal changes the independent readers do not decode, but it can only list what ExifTool understands. Unknown namespaces are never ignored, so an unexplained change fails the item.',
    'Companion forms that cannot hold a value exactly are removed (or the item is refused), never truncated: IPTC byte limits, text outside a known IPTC character set, ASCII-only EXIF when requested, and an EXIF copyright with an editor part. The XMP value is always complete.',
    'Minimise deletes every Exif, XMP, IPTC and Photoshop block and comment from a closed list of known deletions and keeps the encoded image, JFIF, Adobe and ICC segments plus the independently read Exif Orientation, YCbCrPositioning, ColorSpace and an allow-listed InteropIndex; ExifTool adds a closed set of mandatory Exif values that are declared and proved. A Gamma tag or an XMP rendering value that disagrees with Exif refuses the item. Unknown application segments stay byte for byte and are listed. It is not anonymisation.',
    'Metadata Working Group behaviour is applied where stated (UTF-8 text, creator joins, keyword replacement, an IPTC digest next to XMP); this is not a claim of MWG compliance, and the physical meaning of the EXIF, IPTC and XMP values stays what the file says.',
    'ExifTool 13.55 (production release) runs through the system Perl with a clean fixed environment and no configuration; assignments are group-qualified catalogue names with the value as the whole argument, never read from authored input, and ExifTool never overwrites an existing file, a capture or an original.']


# ---------------------------------------------------------------- planning
def plan(document):
    op = document.get('operation')
    declared = options.WRITE_OPTIONS[op]
    extra = sorted(set(document) - {'version', 'operation'} - set(declared))
    if extra:
        fail('UNKNOWN_ARGUMENT', 'unsupported keys for ' + op, '$', keys=extra)
    if document.get('version') != VERSION:
        fail('UNSUPPORTED_VERSION', 'expected ' + VERSION, '$.version')
    p = validate_arguments(declared, {k: v for k, v in document.items() if k in declared})
    media = narrow_media(p['media'], document['media'], op)
    out = {'version': PLAN_VERSION, 'operation': op, 'media': media}
    try:
        if op == 'editMetadata':
            global_edits = {f: edits.normalise_edit(f, p['edits'][f], '$.edits.' + f) for f in writes.fields() if f in p['edits']}
            if not global_edits:
                fail('EDIT_INVALID', 'edits needs at least one field', '$.edits')
            item_edits = []
            ids = [i['id'] for i in media['items']] if media['kind'] == 'items' else []
            for index, entry in enumerate(p.get('itemEdits', [])):
                at = '$.itemEdits[%d]' % index
                if media['kind'] != 'items':
                    fail('ITEM_EDITS_NEED_ITEMS', 'per-item edits need explicit media items; a folder\'s items are not known when the document is authored', at + '.item')
                if entry['item'] not in ids:
                    fail('UNKNOWN_ITEM', 'itemEdits names an item that is not in media.items', at + '.item', value=entry['item'][:64], items=ids[:20])
                if any(e['item'] == entry['item'] for e in item_edits):
                    fail('DUPLICATE_ITEM_EDIT', 'an item has more than one itemEdits entry', at + '.item', value=entry['item'])
                item_edits.append({'item': entry['item'], 'edits': {f: edits.normalise_edit(f, entry['edits'][f], '%s.edits.%s' % (at, f)) for f in writes.fields() if f in entry['edits']}})
                if not item_edits[-1]['edits']:
                    fail('EDIT_INVALID', 'an itemEdits entry needs at least one field', at + '.edits')
            out.update(edits=global_edits, itemEdits=item_edits, policies=edits.normalise_policies(p.get('policies')))
        elif op in e4copy.OPERATIONS:
            out.update(e4copy.static_plan(op, p, media))
        elif op in e3write.OPERATIONS:
            block = e3write.static_plan(op, p, media)
            if 'planFile' not in block:
                block['arguments'] = e3write.json_safe({k: v for k, v in p.items() if k not in ('media', 'apply', 'plan')})
            out.update(apply=p.get('apply', 'write'), e3=block)
        else:
            order = list(writes.categories()) + ['minimise']
            chosen = [c for c in order if c in p['categories']]
            if 'minimise' in chosen and len(chosen) > 1:
                fail('INVALID_ARGUMENT', 'minimise is exclusive: it already removes every concrete category', '$.categories')
            out.update(categories=chosen)
    except edits.PlanError as error:
        fail(error.code, error.message, error.location, **error.observed)
    if op in e4copy.OPERATIONS:
        out.update(settings={'nativeArguments': listing.FIXED, 'writeProtocol': 'one ExifTool process per item (the E2 copy writer); argument-array assignment -GROUP:TAG=value of typed values chosen by Schemaxis; -o to a private stage; no -tagsFromFile, no -m, no -overwrite_original', 'threads': 1, 'userConfiguration': False},
                   budget={'maxItems': mediaset.MAX_ITEMS, 'maxItemBytes': mediaset.ITEM_BYTES, **mediaset.large_bounds(media), 'maxTotalBytes': mediaset.TOTAL_BYTES, 'maxScans': jpegwrite.MAX_SCANS},
                   catalogue={'version': catalogue.VERSION_E4, 'sha256': catalogue.digest(catalogue.VERSION_E4)}, writes={'version': e4copy.VERSION, 'sha256': e4copy.digest(), 'baseVersion': writes.VERSION, 'baseSha256': writes.digest()},
                   losses=LOSSES + e4copy.LOSSES)
        return out
    if op in e3write.OPERATIONS:
        out.update(settings={'nativeArguments': listing.FIXED, 'writeProtocol': 'one ExifTool process per item; argument-array assignment -GROUP:TAG=value under -n (raw values computed by Schemaxis); -o to a private stage; no -m, no -overwrite_original, no -geotag, no -geosync', 'threads': 1, 'userConfiguration': False},
                   budget={'maxItems': mediaset.MAX_ITEMS, 'maxItemBytes': mediaset.ITEM_BYTES, **mediaset.large_bounds(media), 'maxTotalBytes': mediaset.TOTAL_BYTES, 'maxScans': jpegwrite.MAX_SCANS},
                   catalogue={'version': catalogue.VERSION_E3, 'sha256': catalogue.digest(catalogue.VERSION_E3)}, writes={'version': e3writes.VERSION, 'sha256': e3writes.digest()}, losses=LOSSES + e3write.LOSSES[op])
        return out
    out.update(settings={'nativeArguments': listing.FIXED, 'writeProtocol': 'one ExifTool process per item; argument-array assignment -TAG=value; -o to a private stage; no -m, no -overwrite_original, no -n', 'threads': 1, 'userConfiguration': False},
               budget={'maxItems': mediaset.MAX_ITEMS, 'maxItemBytes': mediaset.ITEM_BYTES, **mediaset.large_bounds(media), 'maxTotalBytes': mediaset.TOTAL_BYTES, 'maxScans': jpegwrite.MAX_SCANS},
               catalogue={'version': catalogue.VERSION_MWG, 'sha256': catalogue.digest(catalogue.VERSION_MWG)}, writes={'version': writes.VERSION, 'sha256': writes.digest()}, losses=LOSSES)
    return out


def narrow_media(media, authored, op=None):
    """The shared media envelope, narrowed to JPEG files without sidecars (sidecar writing is a separate family; applySidecar reads its sidecars as the declared source)."""
    planned = mediaset.plan_media(media)
    sidecars_ok = op == 'applySidecar'
    if planned['kind'] == 'items':
        for index, item in enumerate(planned['items']):
            at = '$.media.items[%d]' % index
            if 'sidecar' in item and not sidecars_ok:
                fail('WRITE_SIDECAR_UNSUPPORTED', 'writing beside an XMP sidecar is not offered yet (for any container); the sidecar would silently disagree', at + '.sidecar')
            if Path(item['path']).suffix.lower() not in mediaset.RASTER_SUFFIXES:
                fail('INVALID_PHOTO_SOURCE', 'select a .jpg, .jpeg, .tif, .tiff, .dng, .png, .webp, .heic, .heif or .avif file: only these image files are written', at + '.path')
        return planned
    folder = planned['folder']
    if '.xmp' in folder['extensions'] and 'extensions' in authored['folder'] and not sidecars_ok:
        fail('INVALID_ARGUMENT', 'only image files are written (.jpg, .jpeg, .tif, .tiff, .dng, .png, .webp, .heic, .heif, .avif); XMP sidecars are not', '$.media.folder.extensions')
    folder['extensions'] = [e for e in folder['extensions'] if e in mediaset.RASTER_SUFFIXES]
    if 'sidecars' not in authored['folder'] and not sidecars_ok:
        folder['sidecars'] = 'none'
    return planned


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
    if p['operation'] in e3write.OPERATIONS:
        found.update(e3write.reusable_inputs(p))
    if p['operation'] in e4copy.OPERATIONS:
        found.update(e4copy.reusable_inputs(p))
    return found


def schema():
    from schemaxis.schema import DRAFT, argument_schema, object_schema

    def branch(op, required):
        return object_schema({'version': {'const': VERSION}, 'operation': {'const': op}, **{k: argument_schema(v) for k, v in options.WRITE_OPTIONS[op].items()}}, ['version', 'operation', *required])
    branches = [branch('editMetadata', ['media', 'edits']), branch('removeMetadata', ['media', 'categories']), branch('correctTime', ['media']), branch('setLocation', ['media']), branch('geotagFromTrack', ['media']),
                branch('copyMetadata', ['media', 'source', 'transfer']), branch('applySidecar', ['media', 'source', 'transfer'])]
    declared = {}
    for o in options.WRITE_OPTIONS.values():
        for k, v in o.items():
            variants = declared.setdefault(k, [])
            if v not in variants:
                variants.append(v)
    # A key that two operations declare with different shapes (`policies`) is the union of the shapes in operation order, so the flat view accepts every branch's
    # document and the E2 shape stays the first option; each branch carries its own exact schema.
    properties = {'operation': {'enum': list(OPERATIONS)}, **{k: argument_schema(v[0] if len(v) == 1 else {'type': 'union', 'options': [{a: b for a, b in x.items() if a != 'required'} for x in v]}) for k, v in declared.items()}}
    return {'properties': properties, 'oneOf': branches}


# ---------------------------------------------------------------- evidence helpers
def read_json(directory, name): return wb.read_json(directory, name)
def encode(value): return legacy.encode_json(value)
def digest_of(directory, name, limit=JSON_LIMIT): return legacy.sha(legacy.bounded(directory / name, limit=limit))
def limit_of(name): return mediaset.item_limit(name) if name.startswith((CAPTURED + '/', REJECTED + '/', PHOTOS + '/', STAGE + '/')) else 72 * 1024 * 1024 if name.startswith('inputs/') else JSON_LIMIT
def captured_file(item_id, ext='.jpg'): return '%s/%s%s' % (CAPTURED, item_id, ext)
def stage_file(item_id, ext='.jpg'): return '%s/%s%s' % (STAGE, item_id, ext)


def ext_of(entry):
    """The extension of an item's capture, stage and published names: its captured file's own (E5 containers are named by what they are; a JPEG keeps its `.jpg`)."""
    return Path(entry['file']).suffix if entry.get('file') else '.jpg'


def exts_of(captured): return {e['id']: ext_of(e) for e in captured['items']}
def write_stage(item_id): return 'write-' + item_id


bound_of, fsize_of = wb.bound_of, wb.fsize_of


def launcher(stage, command, names):
    """The trusted launcher of one stage: it hashes every input it names and then replaces itself with the fixed native command."""
    environment = {'LANG': 'C', 'LC_ALL': 'C', **({'LD_TRACE_LOADED_OBJECTS': '1'} if stage == 'libraries' else {})}
    return ('import hashlib,json,os,resource,stat\nfrom pathlib import Path\n'
            + 'command=%r\nnames=%r\nenvironment=%r\nbindings={"files":{}}\n' % (command, list(names), environment)
            + 'resource.setrlimit(resource.RLIMIT_CPU,(600,600))\nresource.setrlimit(resource.RLIMIT_FSIZE,(%d,%d))\nresource.setrlimit(resource.RLIMIT_AS,(4294967296,4294967296))\nresource.setrlimit(resource.RLIMIT_CORE,(0,0))\n' % (fsize_of(names), fsize_of(names))
            + 'for name in names:\n    fd=os.open(name,os.O_RDONLY|os.O_NOFOLLOW|getattr(os,"O_NONBLOCK",0))\n'
            + '    with os.fdopen(fd,"rb") as stream:\n        info=os.fstat(stream.fileno())\n'
            + '        if not stat.S_ISREG(info.st_mode) or info.st_size>%d: raise ValueError("invalid native input")\n' % bound_of(names)
            + '        h=hashlib.sha256();count=0\n        for block in iter(lambda:stream.read(1<<20),b""):\n            count+=len(block);h.update(block)\n'
            + '        if count!=info.st_size: raise ValueError("native input changed while read")\n    bindings["files"][name]=h.hexdigest()\n'
            + 'Path(%r).write_text(json.dumps(bindings,sort_keys=True))\n' % (stage + '-inputs.json')
            + 'os.execve(command[0],command,dict(environment))\n')


def stage_command(script, stage, names, args=(), item=None, ext='.jpg'):
    base = [PERL, script, '-config', '']
    if stage == 'version':
        return [PERL, script, '-config', '', '-ver']
    if stage == 'libraries':
        return [PERL, '-e', '1']
    if stage == 'modules':
        return [PERL, '-I', str(Path(script).parent / 'lib'), '-e', legacy.MODULE_PROBE]
    if stage in ('before', 'after'):
        return [PERL, script, *listing.FIXED, *names]
    return [*base, *args, '-o', stage_file(item, ext), captured_file(item, ext)]


def run_stage(directory, stage, command, names, timeout):
    path = directory / (stage + '-launcher.py')
    path.write_text(launcher(stage, command, names))
    return execute([sys.executable, str(path)], directory, stage, timeout, {'LANG': 'C.UTF-8'})


def evidence_names(captured, written, rejected, after=True, failures=()):
    names = {'authored.json', 'plan.json', 'captures.json', 'runtime.json'}
    for entry in captured['items']:
        if entry['fault'] is None:
            names.add(entry['file'])
            if entry['sidecar']:
                names.add(entry['sidecar']['file'])
    for stage in [s for s in STATIC_STAGES if after or s != 'after']:
        names |= {stage + x for x in ('-launcher.py', '-inputs.json', '-submission.json', '.stdout', '.stderr')}
    for item_id in written:
        stage = write_stage(item_id)
        names |= {stage + x for x in ('-launcher.py', '-inputs.json', '.stdout', '.stderr')}
        names |= {stage + ('-failure.json' if item_id in failures else '-submission.json')}
    exts = exts_of(captured)
    names |= {'%s/%s%s' % (REJECTED, i, exts[i]) for i in rejected}
    names |= e3write.input_names(captured) | e4copy.input_names(captured)
    return names


# ---------------------------------------------------------------- per-item admission and planning (shared by run and verify)
def edit_fields(p):
    names = set(p.get('edits', {}))
    names |= {f for entry in p.get('itemEdits', []) for f in entry['edits']}
    return [f for f in writes.fields() if f in names]


def item_edits_of(p, item_id):
    merged = dict(p['edits'])
    for entry in p.get('itemEdits', []):
        if entry['item'] == item_id:
            merged.update(entry['edits'])
    return merged


def refusal_fault(error, item):
    return wb.fault_dict(error.code, error.message, error.location if error.location != '$' else item['file'], **error.observed)


CONTAINER_WRITES = ('tiff', 'dng', 'png', 'webp', 'heif')
CONTAINER_OPERATIONS = ('editMetadata', 'removeMetadata', *e3write.OPERATIONS, *e4copy.OPERATIONS)       # E5: every writing operation is admitted for the other containers; each planner refuses precisely per item


def admit(directory, p, captured):
    """Independent admission of every captured item: structure walk, payload read and (before any native call) the item's edit or removal plan."""
    items = []
    for entry in captured['items']:
        item = {**entry, 'status': 'refused' if entry['fault'] else 'ok', 'walk': None, 'located': None, 'payloads': None, 'bytes_': None, 'plan': None, 'args': None}
        items.append(item)
        if entry['fault'] is not None:
            continue
        data = legacy.bounded(directory / entry['file'], limit=mediaset.item_limit(entry['file']))
        if legacy.sha(data) != entry['sha256'] or len(data) != entry['bytes']:
            fail('VERIFICATION_FAILED', 'a retained captured item differs from its capture record', entry['file'])
        item['bytes_'] = data
        try:
            if entry['container'] not in ('jpeg', *CONTAINER_WRITES) or (entry['container'] != 'jpeg' and p['operation'] not in CONTAINER_OPERATIONS):
                raise jpegwrite.Refused('UNSUPPORTED_WRITE_CONTAINER', 'only JPEG files are written' if entry['container'] == 'jpeg' or entry['container'] not in CONTAINER_WRITES else
                                        'this operation writes JPEG files only; %s is written by editMetadata and removeMetadata' % entry['container'], container=entry['container'])
            if entry['sidecar'] and p['operation'] != 'applySidecar':
                raise jpegwrite.Refused('WRITE_SIDECAR_PRESENT', 'a sidecar is paired with this file and writing only the JPEG would leave the two silently disagreeing')
            if entry['container'] == 'jpeg':
                item['walk'] = jpegwrite.walk(data)
                item['located'] = containers.locate(data)
            else:
                item['located'] = e5edit.admit(data, entry.get('relative'))
            item['payloads'] = records.Payloads(item['located'])
        except (jpegwrite.Refused, containers.Refused) as error:
            item.update(status='refused', fault=wb.fault_dict(error.code, error.message, entry['file'], **getattr(error, 'observed', {})))
    return items


def digest_present(item):
    if item['walk'] is None:
        return e5edit.digest_present(item['located'])
    return 0x0425 in proofs.iim_resources(item['walk'], item['bytes_'])


def plan_items(p, items, before, ctx=None):
    """Item plans from the independent read and the native before listing; any refusal turns the item into a refused outcome (the others continue)."""
    if p['operation'] in e3write.OPERATIONS:
        return e3write.plan_items(p, items, before, ctx)
    if p['operation'] in e4copy.OPERATIONS:
        return e4copy.plan_items(p, items, before, ctx, ctx.directory)
    for item in items:
        if item['status'] != 'ok':
            continue
        try:
            record = before[item['file']]
            problem = native_input_problems(record)
            if problem:
                raise edits.Refusal(problem[0], problem[1])
            if p['operation'] == 'editMetadata':
                item['plan'] = edits.plan_item(item_edits_of(p, item['id']), item['payloads'], p['policies'], digest_present(item))
                item['plan']['kind'] = 'edit'
                e5edit.creation_guard(item['container'], item['payloads'], item['plan'])
                e5edit.empty_item_guard(item['container'], item['payloads'], item['plan'])
                e5edit.psir_tail_guard(item, item['plan'])
                e5edit.tiff_iptc_guard(item['container'], item['plan'], digest_present(item), item['located'])
                _, fields, _ = records.build(item['located'], list(item['plan']['fields']), None, catalogue.VERSION_MWG)
                item['beforeFields'] = {name: {'state': f['state'], 'reconciliation': f['reconciliation']} for name, f in fields.items()}
                checked, mismatches = listing.anchors(item, fields, {'image': listing.index(record), 'sidecar': None})
                if mismatches:
                    raise edits.Refusal('NATIVE_ANCHOR_MISMATCH', 'ExifTool and the independent reader disagree about this capture, so it is not rewritten', item['file'], count=len(mismatches), mismatches=mismatches[:listing.ANCHOR_REPORT])
                item['plan']['anchorsChecked'] = checked
                qualified = xmp_qualifier_loss(item)
                if qualified:
                    raise edits.Refusal('XMP_QUALIFIERS_WOULD_BE_LOST', 'an XMP value this edit rewrites carries qualifiers (item attributes or qualifier structures) that the rewrite would silently drop, so the item is refused rather than flattened',
                                        '$.edits.' + qualified['field'], property=qualified['property'], qualifiers=qualified['count'])
                item['args'] = edits.assignments(item['plan'])
            else:
                item['plan'] = removal.plan_item(p['categories'], item, record)
                item['plan']['kind'] = 'remove'
                e5edit.psir_tail_guard(item, item['plan'])
                e5edit.tiff_iptc_guard(item['container'], item['plan'], digest_present(item), item['located'])
                item['args'] = removal.assignments(item['plan'])
        except edits.Refusal as error:
            item.update(status='refused', fault=wb.fault_dict(error.code, error.message, item['file'] if error.location == '$' else error.location, **error.observed), plan=None, args=None)


def xmp_qualifier_loss(item):
    """The first rewritten XMP property of the plan whose capture carries qualifiers that a rewrite would drop, or ``None``."""
    xmp = item['located']['xmp']
    if not xmp:
        return None
    wanted = {}
    for name, f in item['plan']['fields'].items():
        spec = {d['family']: d for d in writes.fields()[name]['destinations']}.get('xmp')
        if spec and any(d['family'] == 'xmp' and d['state'] in ('write', 'delete') for d in f['destinations']):
            wanted.setdefault(spec['property'], name)
    found = xmp_reader.qualifiers(xmp[0], set(wanted))
    for prop in sorted(found):
        return {'field': wanted[prop], 'property': prop, 'count': found[prop]}
    return None


def exif_scope(plan_):
    """``(entries the plan names, IFDs it deletes wholesale)`` for the independent non-target Exif comparison."""
    targets, deleted = set(), set()
    if plan_['kind'] in e3write.KINDS:
        return {tuple(t) for t in plan_.get('exifTargets', ())}, set()
    if plan_['kind'] == 'edit':
        by_write = {d['write']: d for name in plan_['fields'] for d in writes.fields()[name]['destinations']}
        for f in plan_['fields'].values():
            for d in f['destinations']:
                if d['family'] == 'exif' and d['state'] in ('write', 'delete'):
                    spec = by_write[d['write']]
                    targets.add((spec['ifd'], int(spec['tag'], 16)))
    else:
        deleted = {{'GPS:all': 'GPS', 'IFD1:all': 'IFD1'}[b] for b in plan_['blocks'] if b in ('GPS:all', 'IFD1:all')}
        targets = {(e['ifd'], int(e['tag'], 16)) for e in plan_['selectors'].get('exif', []) if '%s:%s' % (e['ifd'], e['tag']) in plan_['found']['exif']}
        if 'MakerNotes:all' in plan_['blocks']:
            targets.add(('ExifIFD', 0x927C))
    return targets, deleted


def native_input_problems(record):
    if record['fault']:
        return (record['fault']['code'], record['fault']['message'])
    if record['warnings'] or record['errors']:
        return ('WRITE_INPUT_NATIVE_WARNING', 'ExifTool reports a warning or error for the capture, so it is not rewritten: ' + str((record['warnings'] + record['errors'])[0])[:160])
    return None


def apply_before(p, items, stdout, extra=None):
    """Parse the retained native listing of the captures and refuse items whose input is not clean or whose catalogue targets disagree with the native reader."""
    names = [i['file'] for i in items if i['status'] == 'ok'] + list(extra or ())
    try:
        parsed = listing.parse(stdout, names) if names else []
    except (ValueError, UnicodeDecodeError, RecursionError) as error:
        fail('NATIVE_OBSERVATION_MISMATCH', 'the native listing is not the strict bounded listing of the captured files: ' + str(error)[:200], 'before')
    return dict(zip(names, parsed))




# ---------------------------------------------------------------- proofs and outcome of one item (shared by run and verify)
EXPECTED_STDOUT = b'    1 image files created\n'


def thumbnail(located):
    """SHA-256 and length of the IFD1 thumbnail JPEG inside the Exif payload, or ``None``."""
    from schemaxis.adaptors.exiftool import tiff
    if not located['exif']:
        return None
    payload = located['exif'][0]
    try:
        group = tiff.walk(payload)['ifds'].get('IFD1')
    except tiff.Damaged:
        return None
    if not group or group[0] != 'ok':
        return None
    start = next((e.values() for e in group[1] if e.tag == 0x0201), None)
    size = next((e.values() for e in group[1] if e.tag == 0x0202), None)
    if not start or not size:
        return None
    data = payload[start[0]:start[0] + size[0]]
    return {'sha256': legacy.sha(data), 'bytes': len(data)}


def maker_note_size(payloads):
    state = payloads.exif
    if state[0] != 'ok':
        return None
    group = state[1]['ifds'].get('ExifIFD')
    if not group or group[0] != 'ok':
        return None
    found = [e for e in group[1] if e.tag == 0x927C]
    return len(found[0].raw or b'') if found else None


def evaluate(p, item, index, data, after_record, write):
    """The outcome of one item from its capture, the written bytes, the fresh native listing of them and the write evidence."""
    at = '$.items[%d]' % index
    out = {'id': item['id'], 'order': item['order'], 'status': None, 'fault': None, 'proofs': None}
    if item['status'] != 'ok':
        out.update(status='refused', fault=item['fault'])
        return out
    if write['failure']:
        out.update(status='failed', fault=wb.fault_dict(write['failure']['code'], write['failure']['message'], at, **write['failure'].get('observed', {})))
        return out
    plan_ = item['plan']
    if plan_['kind'] == 'transfer':
        return e4copy.evaluate(p, item, index, data, after_record, out)
    declared = {k for k, v in plan_['declared'].items() if v}
    problems, proof, maker_effects = [], {'P': {}, 'R': {}, 'N': {}}, []
    item.update(outputBytes=len(data), outputSha256=legacy.sha(data))
    if item['walk'] is None:
        return evaluate_container(p, item, index, data, after_record, out, at)
    try:
        walk_out = jpegwrite.walk(data)
        item['outputWalk'] = walk_out
        located_out = containers.locate(data)
        payloads_out = records.Payloads(located_out)
    except (jpegwrite.Refused, containers.Refused) as error:
        out.update(status='failed', fault=wb.fault_dict('OUTPUT_STRUCTURE_INVALID', 'the written file is not a JPEG that the strict reader admits: ' + error.message, at + '.image', cause=error.code))
        return out
    # P: the encoded image and the rendering segments
    problems = []
    found = jpegwrite.preservation(item['walk'], walk_out, item['bytes_'], data, declared)
    problems += [proofs.problem(f['code'], f['message'], at + '.image', **{k: v for k, v in f.items() if k not in ('code', 'message')}) for f in found]
    thumb_in, thumb_out = thumbnail(item['located']), thumbnail(located_out)
    if thumb_in and 'thumbnail' not in declared and thumb_in != thumb_out:
        problems.append(proofs.problem('THUMBNAIL_CHANGED', 'the embedded thumbnail bytes differ from the capture', at + '.image'))
    notes_in, notes_out = maker_note_size(item['payloads']), maker_note_size(payloads_out)
    if notes_in is not None and not (plan_['kind'] == 'remove' and plan_['found']['makerNote']) and notes_in != notes_out:
        problems.append(proofs.problem('MAKERNOTE_CHANGED', 'the maker note size changed', at + '.image', before=notes_in, after=notes_out))
    tail_in = item['bytes_'][item['walk']['firstScan']:]
    proof['P'] = {'tailSha256': legacy.sha(tail_in), 'tailBytes': len(tail_in), 'scans': walk_out['scans'], 'process': walk_out['frame']['process'], 'declaredSegments': sorted(declared),
                  'renderingSegments': len(jpegwrite.segments_of(walk_out, 'rendering')), 'codingSegments': len(jpegwrite.segments_of(walk_out, 'coding')), 'thumbnail': thumb_out}
    p_problems, problems = problems, []
    # R: requested values and absence read back independently
    if plan_['kind'] in e3write.KINDS:
        problems += e3write.readback(p, plan_, item, payloads_out, at)
        proof['R'] = e3write.proof_r(plan_)
    elif plan_['kind'] == 'edit':
        before_reads, after_reads = {}, {}
        for name, f in plan_['fields'].items():
            for d in writes.fields()[name]['destinations']:
                before_reads[(name, d['family'])] = next(x for x in f['destinations'] if x['family'] == d['family'])['before']
                after_reads[(name, d['family'])] = edits.read_destination(payloads_out, d)
        problems += proofs.readback(plan_, before_reads, after_reads, at)
        _, fields_out, _ = records.build(located_out, list(plan_['fields']), None, catalogue.VERSION_MWG)
        problems += proofs.concordance(plan_, fields_out, at)
        problems += proofs.iptc_untouched(plan_, item['payloads'], payloads_out, at)
        proof['R'] = {'destinations': len(after_reads), 'fields': sorted(plan_['fields'])}
    elif 'minimise' in plan_:
        problems += removal.minimise_residual(plan_, payloads_out, walk_out, located_out, at)
        proof['R'] = {'closedState': True, 'preserved': plan_['minimise']['preserved'], 'exifRewritten': plan_['minimise']['exifRewritten']}
    else:
        problems += removal.residual_check(plan_, payloads_out, walk_out, at)
        proof['R'] = {'selectors': {k: len(v) if isinstance(v, list) else bool(v) for k, v in plan_['selectors'].items()}}
    if 'minimise' not in plan_:
        targets, deleted = exif_scope(plan_)
        exif_in, exif_out = item['located']['exif'], located_out['exif']
        found_nontarget = proofs.exif_nontarget(item['payloads'], payloads_out, targets, deleted, at, (exif_in[0], exif_out[0]) if len(exif_in) == len(exif_out) == 1 else None, maker_effects)
        problems += e3proofs.exif_problems(found_nontarget) if plan_['kind'] in e3write.KINDS else found_nontarget
    if plan_['kind'] in e3write.KINDS:
        problems += e3proofs.xmp_nontarget(item['payloads'], payloads_out, set(plan_.get('xmpTargets', ())), at)
        problems += e3proofs.iptc_nontarget(item['payloads'], payloads_out, {tuple(t) for t in plan_.get('iptcTargets', ())}, at)
    r_problems, problems = problems, []
    # N: closed native before/after diff
    record = after_record
    if record is None or record['fault'] or record['warnings'] or record['errors']:
        problems.append(proofs.problem('WRITE_OUTPUT_NATIVE_WARNING', 'ExifTool reports a warning or error for the written file', at + '.native', detail=(record['fault']['message'] if record and record['fault'] else str((record['warnings'] + record['errors'])[:2])[:200] if record else 'no listing')))
    else:
        ctx = {'xmpWritten': plan_['xmpWritten'], 'assignCharset': plan_['iptc']['assignCharset'], 'iptcChanged': plan_['iptc']['changed'], 'digest': plan_['iptc']['digest'],
               'afterIimMd5': proofs.iim_md5(walk_out, data), 'thumbnailSame': thumb_in == thumb_out, 'iptcEmptied': proofs.iptc_emptied(item['payloads'], payloads_out)}
        before_record = item['beforeRecord']
        if plan_['kind'] in e3write.KINDS:
            ctx['extra'] = e3proofs.extra_side_effect(plan_)
            checked, mismatches = e3write.after_anchors(p, item, payloads_out, record)
            if mismatches:
                problems.append(proofs.problem('NATIVE_ANCHOR_MISMATCH', 'ExifTool and the independent reader disagree about the written file', at + '.native', mismatches=mismatches[:listing.ANCHOR_REPORT]))
            diff = proofs.native_diff(before_record, record, {'fields': {}}, ctx, extra_targets=() if plan_['kind'] == 'unchanged' else e3proofs.native_targets(plan_))
            proof['N'] = {'anchorsChecked': checked}
        elif plan_['kind'] == 'edit':
            checked, mismatches = listing.anchors(item, fields_out, {'image': listing.index(record), 'sidecar': None})
            if mismatches:
                problems.append(proofs.problem('NATIVE_ANCHOR_MISMATCH', 'ExifTool and the independent reader disagree about the written file', at + '.native', mismatches=mismatches[:listing.ANCHOR_REPORT]))
            diff = proofs.native_diff(before_record, record, plan_, ctx)
            proof['N'] = {'anchorsChecked': checked}
        elif 'minimise' in plan_:
            diff = removal.minimise_diff(before_record, record, plan_['minimise'], not any(s['role'] == 'exif' for s in walk_out['pre']))
            problems += removal.minimise_native_residual(record, at)
        else:
            keys_, groups = removal.native_targets(plan_)
            diff = proofs.native_diff(before_record, record, {'fields': {}}, ctx, extra_targets=keys_, extra_prefixes={g + ':' for g in groups if g != 'MakerNotes'}, extra_group0=('MakerNotes',) if 'MakerNotes:all' in plan_['blocks'] else ())
            problems += removal.native_residual(plan_, record, at)
        if diff['unexplained']:
            problems.append(proofs.problem('NATIVE_UNEXPLAINED_CHANGE', 'a native key changed that is neither a target of the plan nor a declared side effect', at + '.native', changes=diff['unexplained'][:8]))
        item['outputNativeGroups'] = native_groups(record)
        proof['N'].update(targets=diff['targets'], sideEffects=diff['sideEffects'] + maker_effects, renumbered=diff['renumbered'], unexplained=len(diff['unexplained']), keysBefore=len(native_keys(before_record)), keysAfter=len(native_keys(record)))
    problems = r_problems + p_problems + problems     # metadata first: a wrong value or a left-over is reported before an integrity fault
    proof['problems'] = len(problems)
    if problems:
        first = problems[0]
        out.update(status='failed', fault=wb.fault_dict(first['code'], first['message'], first['location'], problems=problems[:8]), proofs=None)
    else:
        out.update(status='written', proofs=proof)
    return out


def evaluate_container(p, item, index, data, after_record, out, at):
    """The outcome of one item of a non-JPEG container: P is the generalised offset-free proof, R and N are the shared proofs with the container's closed side effects."""
    plan_ = item['plan']
    container = item['container']
    proof = {'P': {}, 'R': {}, 'N': {}}
    try:
        located_out = e5edit.admit(data, None)
        payloads_out = records.Payloads(located_out)
    except containers.Refused as error:
        out.update(status='failed', fault=wb.fault_dict('OUTPUT_STRUCTURE_INVALID', 'the written file is not a %s file that the strict reader admits: %s' % (container, error.message), at + '.image', cause=error.code, **error.observed))
        return out
    item['outputLocated'] = located_out
    # P: the offset-free fingerprint of everything that is not an editable metadata slot
    result = e5proof.preserve(item['bytes_'], data, allow=e5edit.allowed(item['located'], plan_))
    p_problems = [proofs.problem(f['code'], f['message'], at + '.image', path=f['path']) for f in result['faults']]
    maker_effects = list(result.get('effects', ()))
    proof['P'] = {'container': container, 'protectedRows': len(item['located']['protected']), 'declaredFamilies': sorted(k for k, v in plan_['declared'].items() if v), 'limitations': item['located']['limitations']}
    # R: requested values (or absence) read back from the output
    problems = []
    e3_kind = plan_['kind'] in e3write.KINDS
    if e3_kind:
        problems += e3write.readback(p, plan_, item, payloads_out, at)
        proof['R'] = e3write.proof_r(plan_)
    elif plan_['kind'] == 'edit':
        before_reads, after_reads = {}, {}
        for name, f in plan_['fields'].items():
            for d in writes.fields()[name]['destinations']:
                before_reads[(name, d['family'])] = next(x for x in f['destinations'] if x['family'] == d['family'])['before']
                after_reads[(name, d['family'])] = edits.read_destination(payloads_out, d)
        problems += proofs.readback(plan_, before_reads, after_reads, at)
        _, fields_out, _ = records.build(located_out, list(plan_['fields']), None, catalogue.VERSION_MWG)
        problems += proofs.concordance(plan_, fields_out, at)
        problems += proofs.iptc_untouched(plan_, item['payloads'], payloads_out, at)
        proof['R'] = {'destinations': len(after_reads), 'fields': sorted(plan_['fields'])}
    elif 'minimise' in plan_:
        problems += removal.minimise_residual_container(plan_, payloads_out, located_out, at)
        proof['R'] = {'closedState': True, 'preserved': plan_['minimise']['preserved'], 'exifRewritten': plan_['minimise']['exifRewritten']}
    else:
        problems += removal.residual_check(plan_, payloads_out, None, at, located=located_out)
        proof['R'] = {'selectors': {k: len(v) if isinstance(v, list) else bool(v) for k, v in plan_['selectors'].items()}}
    if container not in e5edit.TIFF_LIKE and 'minimise' not in plan_:
        targets, deleted = e5edit.exif_targets(plan_)
        exif_in, exif_out = item['located']['exif'], located_out['exif']
        found_nontarget = proofs.exif_nontarget(item['payloads'], payloads_out, targets, deleted, at, (exif_in[0], exif_out[0]) if len(exif_in) == len(exif_out) == 1 else None, [])
        problems += e3proofs.exif_problems(found_nontarget) if e3_kind else found_nontarget
    if e3_kind:
        problems += e3proofs.xmp_nontarget(item['payloads'], payloads_out, set(plan_.get('xmpTargets', ())), at)
        problems += e3proofs.iptc_nontarget(item['payloads'], payloads_out, {tuple(t) for t in plan_.get('iptcTargets', ())}, at)
    r_problems, problems = problems, []
    # N: closed native before/after diff
    record = after_record
    if record is None or record['fault'] or record['warnings'] or record['errors']:
        problems.append(proofs.problem('WRITE_OUTPUT_NATIVE_WARNING', 'ExifTool reports a warning or error for the written file', at + '.native', detail=(record['fault']['message'] if record and record['fault'] else str((record['warnings'] + record['errors'])[:2])[:200] if record else 'no listing')))
    else:
        ctx = {'xmpWritten': plan_['xmpWritten'], 'assignCharset': plan_['iptc']['assignCharset'], 'iptcChanged': plan_['iptc']['changed'], 'digest': plan_['iptc']['digest'],
               'afterIimMd5': e5edit.iim_md5(located_out), 'thumbnailSame': True, 'iptcEmptied': proofs.iptc_emptied(item['payloads'], payloads_out), 'extra': e5edit.side_effect(container, item['located'], located_out)}
        before_record = item['beforeRecord']
        if e3_kind:
            container_rule, plan_rule = ctx['extra'], e3proofs.extra_side_effect(plan_)
            ctx['extra'] = lambda key, a, b: plan_rule(key, a, b) or container_rule(key, a, b)
            checked, mismatches = e3write.after_anchors(p, item, payloads_out, record)
            if mismatches:
                problems.append(proofs.problem('NATIVE_ANCHOR_MISMATCH', 'ExifTool and the independent reader disagree about the written file', at + '.native', mismatches=mismatches[:listing.ANCHOR_REPORT]))
            diff = proofs.native_diff(before_record, record, {'fields': {}}, ctx, extra_targets=() if plan_['kind'] == 'unchanged' else e3proofs.native_targets(plan_))
            proof['N'] = {'anchorsChecked': checked}
        elif plan_['kind'] == 'edit':
            checked, mismatches = listing.anchors(item, fields_out, {'image': listing.index(record), 'sidecar': None})
            if mismatches:
                problems.append(proofs.problem('NATIVE_ANCHOR_MISMATCH', 'ExifTool and the independent reader disagree about the written file', at + '.native', mismatches=mismatches[:listing.ANCHOR_REPORT]))
            diff = proofs.native_diff(before_record, record, plan_, ctx)
            proof['N'] = {'anchorsChecked': checked}
        elif 'minimise' in plan_:
            diff = removal.minimise_diff(before_record, record, plan_['minimise'], not located_out['exif'], ctx['extra'])
            problems += removal.minimise_native_residual(record, at, set(plan_['minimise']['textKeywords']))
        else:
            keys_, groups = removal.native_targets(plan_)
            diff = proofs.native_diff(before_record, record, {'fields': {}}, ctx, extra_targets=keys_, extra_prefixes={g + ':' for g in groups if g != 'MakerNotes'})
            problems += removal.native_residual(plan_, record, at)
        if diff['unexplained']:
            problems.append(proofs.problem('NATIVE_UNEXPLAINED_CHANGE', 'a native key changed that is neither a target of the plan nor a declared side effect', at + '.native', changes=diff['unexplained'][:8]))
        item['outputNativeGroups'] = native_groups(record)
        proof['N'].update(targets=diff['targets'], sideEffects=diff['sideEffects'] + maker_effects, renumbered=diff['renumbered'], unexplained=len(diff['unexplained']), keysBefore=len(native_keys(before_record)), keysAfter=len(native_keys(record)))
    problems = r_problems + p_problems + problems     # metadata first: a wrong value or a left-over is reported before an integrity fault
    proof['problems'] = len(problems)
    if problems:
        first = problems[0]
        out.update(status='failed', fault=wb.fault_dict(first['code'], first['message'], first['location'], problems=problems[:8]), proofs=None)
    else:
        out.update(status='written', proofs=proof)
    return out


def native_keys(record): return sorted(proofs.native_map(record))


def native_groups(record):
    found = {}
    for key in proofs.native_map(record):
        found.setdefault(key[1], []).append(key[2])
    return {g: sorted(n)[:64] for g, n in sorted(found.items())}


# ---------------------------------------------------------------- publications
def item_row(p, item, outcome, index):
    row = {'id': item['id'], 'order': item['order'], 'status': outcome['status'], 'artifactIndex': index,
           'source': {'path': item['relative'], 'bytes': item['bytes'], 'sha256': item['sha256'], 'container': item['container']}}
    if outcome['status'] == 'planned':
        row.update(artifactIndex=None, outcome=item['plan']['outcome'])
        return row
    if outcome['status'] != 'written':
        row['fault'] = outcome['fault']
        return row
    plan_ = item['plan']
    row['output'] = {'file': '%s/%s%s' % (PHOTOS, item['id'], ext_of(item)), 'bytes': item['outputBytes'], 'sha256': item['outputSha256']}
    row['arguments'] = item['args']
    row['proofs'] = outcome['proofs']
    if plan_['kind'] == 'transfer':
        row.update(e4copy.row_extra(p, item, outcome))
    elif plan_['kind'] in e3write.KINDS:
        row.update(e3docs.row_extra(p, item, outcome))
    elif plan_['kind'] == 'edit':
        row['beforeConcordance'] = item['beforeFields']
        row['iptc'] = {k: plan_['iptc'][k] for k in ('state', 'charset', 'assignCharset', 'created', 'digest')}
        row['fields'] = {}
        losses = []
        for name, f in plan_['fields'].items():
            row['fields'][name] = {'action': f['action'], 'value': f['value'], 'otherLanguages': f['otherLanguages'], 'losses': f['losses'],
                                   'destinations': [{k: v for k, v in d.items() if k in ('family', 'write', 'state', 'reason', 'limit', 'bytes', 'untouched') } for d in f['destinations']]}
            losses += f['losses']
        row['losses'] = losses
    else:
        row['removed'] = {'categories': plan_['categories'], 'nothingToRemove': not plan_['present'], 'found': plan_['found'], 'blocks': plan_['blocks'], 'nativeDeletions': plan_['observed']}
        if 'minimise' in plan_:
            row['removed']['minimise'] = plan_['minimise']
    return row


def outcome_document(row, op):
    return {'version': REPORT_VERSION, 'operation': op, 'item': row['id'], 'status': row['status'], 'image': False, 'fault': row.get('fault'),
            'statement': 'This is the truthful outcome of one item of the set, kept at its stable slot. It is not an image and nothing was published for it.'}


def documents(p, rows, items, outcomes, ctx=None):
    """Every derived publication as ``{name: bytes}`` from the plan, the manifest rows and the per-item outcomes."""
    op = p['operation']
    table = []
    for index, (item, outcome) in enumerate(zip(items, outcomes)):
        table.append(item_row(p, item, outcome, index))
    written = [r for r in table if r['status'] in ('written', 'planned')]          # 'planned' only occurs in a plan-only E3 run
    manifest_items = [{'id': r['id'], 'status': 'ok' if r['status'] in ('written', 'planned') else 'fault', 'bytes': r['source']['bytes'], 'sha256': r['source']['sha256'], 'fault': r.get('fault'), 'sidecar': i['sidecar']} for r, i in zip(table, items)]
    manifest = wb.build_manifest(p, rows, manifest_items)
    by_id = {r['id']: r for r in table}
    for entry in manifest['entries']:
        r = by_id.get(entry.get('id'))
        if entry['role'] == 'item' and r is not None:
            entry.update(outcome=r['status'], artifactIndex=r['artifactIndex'])
            if r['status'] != 'written':
                entry['image'] = False
    plan_only = p.get('apply') == 'plan'
    counts = {'items': len(table), 'written': len(written), 'refused': sum(1 for r in table if r['status'] == 'refused'), 'failed': sum(1 for r in table if r['status'] == 'failed')}
    if plan_only:
        counts = {'items': len(table), 'planned': len(written), 'refused': counts['refused']}
    status = 'complete' if len(written) == len(table) and manifest['status'] == 'complete' else 'partial'
    manifest['status'], manifest['writeCounts'] = status, counts
    manifest['slots'] = ('this plan-only run publishes documents only: there are no item slots and nothing was written' if plan_only else
                         'artifact slot i is the i-th item of this manifest (plan order for a list, byte-order names for a folder): its published JPEG, or its outcome document (never an image); report documents follow the slots')
    base = {'version': REPORT_VERSION, 'operation': op, 'runtime': RUNTIME, 'catalogue': p['catalogue'], 'writes': p['writes'], 'setStatus': status, 'counts': counts}
    if op in e4copy.OPERATIONS:
        files = {'manifest.json': encode(manifest), **e4copy.documents(p, ctx, base, table, items, outcomes, encode)}
        for r in table:
            if r['status'] not in ('written', 'planned'):
                files['%s/%s.json' % (OUTCOMES, r['id'])] = encode(outcome_document(r, op))
        return files, table
    if op in e3write.OPERATIONS:
        files = {'manifest.json': encode(manifest), **e3docs.documents(p, ctx, base, table, items, outcomes, encode, {'thumbnail': thumbnail, 'maker_note_size': maker_note_size})}
        for r in table:
            if r['status'] not in ('written', 'planned'):
                files['%s/%s.json' % (OUTCOMES, r['id'])] = encode(outcome_document(r, op))
        return files, table
    plan_doc = {**base, 'version': PLAN_VERSION, 'policies': p.get('policies'), 'categories': p.get('categories'), 'edits': p.get('edits'), 'itemEdits': p.get('itemEdits'),
                'items': [{'id': r['id'], 'status': r['status'], **({'fault': r['fault']} if r['status'] == 'refused' else {'arguments': by_item_args(items, r['id'])})} for r in table],
                'statement': 'The native assignments each item receives, decided from the independent read of its capture before any native write. Values are never authored as native options.'}
    report = {**base, 'items': table, 'statement': 'Per-item outcomes with the three proofs. P is about bytes, not pixels; N compares two listings of the same engine; a coherent rewrite of every retained record verifies as consistency, not authenticity.',
              'review': {'observedMetadataOnly': True, 'privacyCertified': False, 'anonymised': False, 'humanReviewRequired': True}, 'losses': LOSSES}
    prefix = 'edit' if op == 'editMetadata' else 'removal'
    files = {'manifest.json': encode(manifest), prefix + '-plan.json': encode(plan_doc), prefix + '-report.json': encode(report)}
    if op == 'removeMetadata':
        files['residual.json'] = encode(residual_document(base, table, items, outcomes))
    for r in table:
        if r['status'] != 'written':
            files['%s/%s.json' % (OUTCOMES, r['id'])] = encode(outcome_document(r, op))
    return files, table


def by_item_args(items, item_id):
    return next((i['args'] for i in items if i['id'] == item_id), None)


def residual_document(base, table, items, outcomes):
    rows = []
    for r, item, outcome in zip(table, items, outcomes):
        if r['status'] != 'written':
            continue
        if item.get('outputWalk') is None:       # a non-JPEG container: the protected fingerprint rows by role replace the JPEG segment list
            located = item['outputLocated']
            roles = {}
            for row in located['protected']:
                roles[row[0]] = roles.get(row[0], 0) + 1
            rows.append({'id': r['id'], 'container': item['container'], 'protectedRowsByRole': dict(sorted(roles.items())), 'metadataSlots': [{k: v for k, v in s_.items() if k in ('family', 'state', 'role', 'count')} for s_ in located['slots']],
                         'limitations': located['limitations'], 'nativeResidual': item['outputNativeGroups'], 'removed': r['removed']})
            continue
        walk_out = item['outputWalk']
        rows.append({'id': r['id'], 'segments': [{'marker': '0x%02X' % s['marker'], 'bytes': s['length'], 'sha256': s['sha256'], 'role': s['role']} for s in walk_out['pre']],
                     'nativeResidual': item['outputNativeGroups'], 'removed': r['removed']})
    return {**base, 'items': rows,
            'limits': ['This is removal for the listed categories in the understood locations: not anonymisation, privacy certification or a claim that nothing identifying remains.',
                       'Not inspected or removed: pixel content (faces, text, scene features, steganographic content), the file name and path, unknown or unrecognised maker notes, ICC profile contents, other application segments kept byte-for-byte, and any embedded content the readers do not understand.',
                       'Segment roles are structural: coding (frame header and tables), rendering (JFIF, Adobe, ICC), exif, xmp, iptc and other. Kept segments are listed with their hashes.']}


def artifacts(directory, p, table):
    """One artifact slot per item in manifest order, then the report documents."""
    out = []
    for r in ([] if p.get('apply') == 'plan' else table):
        if r['status'] == 'written':
            out.append({'file': str(directory / r['output']['file']), 'kind': 'image', 'sha256': r['output']['sha256'],
                        'identity': {'kind': 'image', 'format': r['source']['container'], 'item': r['id']}, 'losses': LOSSES, **({'outcome': r['outcome']} if p['operation'] in e3write.OPERATIONS + e4copy.OPERATIONS else {}),
                        'verificationScope': 'Readback, encoded-image preservation and native diff proofs of this run, recomputed from these bytes; no pixel decode and no authenticity claim.'})
        else:
            name = '%s/%s.json' % (OUTCOMES, r['id'])
            out.append({'file': str(directory / name), 'kind': 'text', 'sha256': digest_of(directory, name), 'identity': {'kind': 'outcome', 'item': r['id'], 'image': False}})
    for name in report_names(p):
        out.append({'file': str(directory / name), 'kind': 'text', 'sha256': digest_of(directory, name)})
    return out


def report_names(p):
    if p['operation'] in e4copy.OPERATIONS:
        return e4copy.names(p)
    if p['operation'] in e3write.OPERATIONS:
        return e3docs.names(p)
    prefix = 'edit' if p['operation'] == 'editMetadata' else 'removal'
    return ['manifest.json', prefix + '-plan.json', prefix + '-report.json'] + (['residual.json'] if p['operation'] == 'removeMetadata' else [])


# ---------------------------------------------------------------- write evidence
def write_failure(directory, item_id, stage_exists):
    """The failure recorded by the retained evidence of one native write, or ``None`` when the write was clean."""
    stage = write_stage(item_id)
    failure_path = directory / (stage + '-failure.json')
    if failure_path.exists():
        recorded = read_json(directory, stage + '-failure.json')
        return {'code': 'NATIVE_WRITE_FAILED', 'message': 'the ExifTool write process did not complete (exit status %s)' % recorded.get('exitCode'), 'observed': {'exitCode': recorded.get('exitCode')}}
    stderr = legacy.bounded(directory / (stage + '.stderr'), limit=legacy.LOG_LIMIT)
    stdout = legacy.bounded(directory / (stage + '.stdout'), limit=legacy.LOG_LIMIT)
    if stderr:
        return {'code': 'NATIVE_WRITE_WARNING', 'message': 'ExifTool wrote to stderr during the write (warnings are faults: no truncation or repair is accepted)', 'observed': {'stderr': stderr.decode('utf-8', 'replace')[:300]}}
    if stdout != EXPECTED_STDOUT or not stage_exists:
        return {'code': 'NATIVE_WRITE_FAILED', 'message': 'ExifTool did not report exactly one image file created', 'observed': {'stdout': stdout.decode('utf-8', 'replace')[:120]}}
    return None


def listing_command(executable, names, stage):
    return stage_command(executable, stage, names)


def native_clean(directory, item):
    return item['status'] == 'ok' and bool(item['args']) and item.get('write') is not None and item['write']['failure'] is None


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
    import math
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
                _, _, after = wb.collect_signature(p)
                if after != signature:
                    fail('MEDIA_FOLDER_CHANGED', 'the media folder changed while its items were captured; run again when it is stable', '$.media.folder.path',
                         changed=sorted({k for k in set(signature) | set(after) if signature.get(k) != after.get(k)})[:20])
            captured = {'source': wb.source_set(p, rows, signature), 'rows': rows, 'items': entries}
            ctx = None
            if p['operation'] in e3write.OPERATIONS:
                inputs = e3write.capture(p, directory, p['media'])
                if inputs:
                    captured['inputs'] = inputs
            if p['operation'] in e4copy.OPERATIONS:
                inputs = e4copy.capture(p, directory, p['media'])
                if inputs:
                    captured['inputs'] = inputs
            atomic_json(directory / 'captures.json', captured)
            if p['operation'] in e3write.OPERATIONS:
                ctx = e3write.Context(p, directory, captured)
            if p['operation'] in e4copy.OPERATIONS:
                ctx = e4copy.Context(p, directory, captured)
            items = admit(directory, p, captured)
            usable = [i for i in items if i['status'] == 'ok']
            if not usable:
                finish_without_writes(directory, p, rows, items, None, ctx)
            names = [i['file'] for i in usable]
            if p['operation'] in e4copy.OPERATIONS:
                names = names + e4copy.extra_native_names(p, ctx, items)
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
            before = apply_before(p, items, before_bytes, e4copy.extra_native_names(p, ctx, items) if p['operation'] in e4copy.OPERATIONS else None)
            for item in items:
                if item['status'] == 'ok':
                    item['beforeRecord'] = before[item['file']]
            plan_items(p, items, before, ctx)
            if not any(i['status'] == 'ok' for i in items):
                finish_without_writes(directory, p, rows, items, None, ctx)
            if p.get('apply') == 'plan':
                return finish_plan_only(directory, p, rows, items, captured, ctx, executable, runtime, entries, checkpoint)
            (directory / STAGE).mkdir(mode=0o700)
            for item in items:
                if item['status'] != 'ok':
                    continue
                item['write'] = None
                if not item['args']:
                    (directory / stage_file(item['id'], ext_of(item))).write_bytes(item['bytes_'])
                    item['write'] = {'native': False, 'failure': None}
                    continue
                checkpoint()
                stage = write_stage(item['id'])
                command = stage_command(executable, stage, [], item['args'], item['id'], ext_of(item))
                failure = None
                try:
                    run_stage(directory, stage, command, [captured_file(item['id'], ext_of(item))], remaining_timeout(timeout))
                except SchemaxisError as error:
                    if error.fault.code != 'RUNNER_FAILED':
                        raise
                    atomic_json(directory / (stage + '-failure.json'), {'exitCode': error.fault.observed.get('exitCode')})
                exists = (directory / stage_file(item['id'], ext_of(item))).is_file()
                failure = write_failure(directory, item['id'], exists)
                item['write'] = {'native': True, 'failure': failure}
            checkpoint()
            if legacy.runtime_identity(directory, executable, checkpoint) != runtime:
                fail('RUNTIME_CHANGED', 'ExifTool, Perl or a dependency changed during the run')
            for entry in entries:
                if entry['fault'] is None and legacy.stream_capture(entry['source'], mediaset.item_limit(entry['source']), 'PHOTO_CHANGED', location='$.media')['sha256'] != entry['sha256']:
                    fail('PHOTO_CHANGED', 'a source item changed during the native run', '$.media', photo=entry['id'])
            atomic_json(directory / 'runtime.json', {'executable': executable, **runtime})
            clean = [i for i in items if i['status'] == 'ok' and i['write']['failure'] is None]
            after_names = [stage_file(i['id'], ext_of(i)) for i in clean if i['write']['native']]
            after = {}
            if after_names:
                checkpoint()
                run_stage(directory, 'after', stage_command(executable, 'after', after_names), after_names, remaining_timeout(timeout))
                if legacy.bounded(directory / 'after.stderr', limit=legacy.LOG_LIMIT):
                    fail('NATIVE_OBSERVATION_MISMATCH', 'the native listing of the written files wrote to stderr', 'after')
                parsed = listing.parse(legacy.bounded(directory / 'after.stdout', limit=listing.MAX_STDOUT + 1), after_names)
                after = dict(zip(after_names, parsed))
            outcomes = []
            for index, item in enumerate(items):
                checkpoint()
                if item['status'] != 'ok':
                    outcomes.append(evaluate(p, item, index, None, None, None))
                    continue
                stage_path = directory / stage_file(item['id'], ext_of(item))
                data = stage_path.read_bytes() if stage_path.is_file() else None
                record = after.get(stage_file(item['id'], ext_of(item))) if item['write']['native'] else item['beforeRecord']
                outcome = evaluate(p, item, index, data, record, item['write']) if (data is not None or item['write']['failure']) else evaluate(p, item, index, b'', None, {'failure': {'code': 'NATIVE_WRITE_FAILED', 'message': 'no output file'}})
                outcomes.append(outcome)
                publish(directory, item, outcome, data)
            for sub in (OUTCOMES,):
                (directory / sub).mkdir(exist_ok=True)
            if not any(o['status'] == 'written' for o in outcomes):
                finish_without_writes(directory, p, rows, items, outcomes, ctx)
            files, table = documents(p, rows, items, outcomes, ctx)
            for name, data in files.items():
                (directory / name).parent.mkdir(exist_ok=True)
                (directory / name).write_bytes(data)
            if (directory / STAGE).is_dir():
                os.rmdir(directory / STAGE)
            rejected = sorted(i['id'] for i, o in zip(items, outcomes) if i['status'] == 'ok' and o['status'] == 'failed' and (directory / REJECTED / (i['id'] + ext_of(i))).is_file())
            written = [i['id'] for i in items if i['status'] == 'ok' and i['write']['native']]
            failures = [i for i in written if (directory / (write_stage(i) + '-failure.json')).exists()]
            evidence = {n: digest_of(directory, n, limit_of(n)) for n in sorted(evidence_names(captured, written, rejected, bool(after_names), failures))}
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


def publish(directory, item, outcome, data):
    """Atomic rename of a proven stage into the run, or of a failed stage into ``rejected/`` (never published as an artifact)."""
    stage_path = directory / stage_file(item['id'], ext_of(item))
    if not stage_path.is_file():
        return
    if outcome['status'] == 'written':
        (directory / PHOTOS).mkdir(exist_ok=True)
        os.replace(stage_path, directory / PHOTOS / (item['id'] + ext_of(item)))
    else:
        (directory / REJECTED).mkdir(exist_ok=True)
        os.replace(stage_path, directory / REJECTED / (item['id'] + ext_of(item)))


def finish_plan_only(directory, p, rows, items, captured, ctx, executable, runtime, entries, checkpoint):
    """``apply: plan``: every read, check and computation has run; publish the plan and its reports with no native write and no item slots."""
    checkpoint()
    if legacy.runtime_identity(directory, executable, checkpoint) != runtime:
        fail('RUNTIME_CHANGED', 'ExifTool, Perl or a dependency changed during the run')
    for entry in entries:
        if entry['fault'] is None and legacy.stream_capture(entry['source'], mediaset.item_limit(entry['source']), 'PHOTO_CHANGED', location='$.media')['sha256'] != entry['sha256']:
            fail('PHOTO_CHANGED', 'a source item changed during the native run', '$.media', photo=entry['id'])
    atomic_json(directory / 'runtime.json', {'executable': executable, **runtime})
    outcomes = planned_outcomes(items)
    (directory / OUTCOMES).mkdir(exist_ok=True)
    files, table = documents(p, rows, items, outcomes, ctx)
    for name, data in files.items():
        (directory / name).parent.mkdir(exist_ok=True)
        (directory / name).write_bytes(data)
    evidence = {n: digest_of(directory, n, limit_of(n)) for n in sorted(evidence_names(captured, [], [], False, ()))}
    atomic_json(directory / 'verification.json', {'executable': executable, 'runtime': RUNTIME, 'planSha256': plan_hash(p), 'artifacts': artifacts(directory, p, table), 'evidence': evidence})
    result = verify(directory, require_result=False, executable=executable)
    checkpoint()
    result['status'] = 'succeeded'
    atomic_json(directory / 'result.json', result)
    return result


def planned_outcomes(items):
    return [{'id': i['id'], 'order': i['order'], 'status': 'planned' if i['status'] == 'ok' else 'refused', 'fault': None if i['status'] == 'ok' else i['fault'], 'proofs': None} for i in items]


def finish_without_writes(directory, p, rows, items, outcomes=None, ctx=None):
    """Every item was refused or failed: write the truthful manifest and outcomes, then fail the run (no success publication)."""
    outcomes = outcomes or [evaluate(p, i, n, None, None, None) for n, i in enumerate(items)]
    (directory / OUTCOMES).mkdir(exist_ok=True)
    files, _ = documents(p, rows, items, outcomes, ctx)
    (directory / 'manifest.json').write_bytes(files['manifest.json'])
    for name, data in files.items():
        if name.startswith(OUTCOMES + '/'):
            (directory / name).write_bytes(data)
    fail('NO_USABLE_ITEMS', 'no item of the media set was written; manifest.json and outcomes/ list every item and its fault', '$.media', items=len(items), firstFaults=[o['fault'] for o in outcomes[:3]])


# ---------------------------------------------------------------- verification
def trusted_runtime(executable): return wb.trusted_runtime(executable)


def membership(directory, p, captured, written, rejected, table):
    """Nothing but the owned evidence, the published slots and their companions may exist in the run directory."""
    from schemaxis.run_paths import MANIFEST
    top = {n for n in evidence_names(captured, written, [], True, [i for i in written if (directory / (write_stage(i) + '-failure.json')).exists()]) if '/' not in n}
    top |= set(report_names(p)) | {'verification.json', 'result.json', 'schema.snapshot.json', MANIFEST, 'job.json'} | {n + '.metadata.json' for n in report_names(p)}
    for path in directory.iterdir():
        if path.name in ('.dispatch', CAPTURED, PHOTOS, OUTCOMES, REJECTED, 'inputs'):
            if path.is_symlink() or not path.is_dir():
                fail('VERIFICATION_FAILED', 'owned member is not a directory', path.name)
        elif path.name not in top or path.is_symlink() or not path.is_file():
            fail('VERIFICATION_FAILED', 'unexpected or nonregular retained member', path.name)
    expected = {
        CAPTURED: sorted(Path(n).name for n in evidence_names(captured, [], [], False) if n.startswith(CAPTURED + '/')),
        PHOTOS: sorted(n for r in table if r['status'] == 'written' for n in (Path(r['output']['file']).name, Path(r['output']['file']).name + '.metadata.json')),
        OUTCOMES: sorted(n for r in table if r['status'] not in ('written', 'planned') for n in (r['id'] + '.json', r['id'] + '.json.metadata.json')),
        REJECTED: sorted(i + exts_of(captured)[i] for i in rejected),
        'inputs': sorted(Path(n).name for n in e3write.input_names(captured) | e4copy.input_names(captured))}
    for sub, names in expected.items():
        folder = directory / sub
        present = sorted(x.name for x in folder.iterdir()) if folder.is_dir() else []
        required = [n for n in names if not n.endswith('.metadata.json')]
        if not set(required) <= set(present) <= set(names):
            fail('VERIFICATION_FAILED', 'retained %s membership differs' % sub, sub, expected=required[:8], observed=present[:8])
        for x in folder.iterdir() if folder.is_dir() else ():
            if x.is_symlink() or not x.is_file():
                fail('VERIFICATION_FAILED', 'a retained member is not a regular file', sub + '/' + x.name)
    for r in table:
        if r['status'] == 'written':
            published, original = directory / r['output']['file'], directory / captured_file(r['id'], exts_of(captured)[r['id']])
            a, b = published.stat(), original.stat()
            if (a.st_dev, a.st_ino) == (b.st_dev, b.st_ino) or a.st_nlink > 1:
                fail('OUTPUT_ALIASES_CAPTURE', 'a published output is the capture itself or shares its inode (a link or hard link)', r['output']['file'])


def fresh_listing(scratch_files, names, executable, stage):
    """A fresh listing of retained bytes with the trusted runtime (the replay of one retained listing)."""
    scratch = Path(tempfile.mkdtemp(prefix='schemaxis-exiftool-'))
    try:
        for name, data in scratch_files.items():
            (scratch / name).parent.mkdir(parents=True, exist_ok=True)
            (scratch / name).write_bytes(data)
        run_stage(scratch, 'version', stage_command(executable, 'version', []), [], remaining_timeout(wb.VERIFY_TIMEOUT))
        if legacy.bounded(scratch / 'version.stdout', 'NATIVE_REPLAY_UNAVAILABLE', 4096).decode('utf-8', 'replace') != '13.55\n':
            fail('NATIVE_REPLAY_UNAVAILABLE', 'the configured ExifTool is not the pinned 13.55 production release', 'version', independentVerified=True)
        run_stage(scratch, stage, stage_command(executable, stage, names), names, remaining_timeout(wb.VERIFY_TIMEOUT))
        if legacy.bounded(scratch / (stage + '.stderr'), limit=legacy.LOG_LIMIT):
            fail('VERIFICATION_FAILED', 'the fresh native replay wrote to stderr', stage)
        return legacy.bounded(scratch / (stage + '.stdout'), limit=listing.MAX_STDOUT + 1)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


def same_listing(fresh, retained, stage):
    if fresh != retained:
        fail('VERIFICATION_FAILED', 'the fresh native replay of the retained bytes differs from the retained %s listing' % stage, stage)


def replay_write(item, data, executable, produced):
    """A fresh write of the retained capture with the retained assignments must reproduce the retained output byte for byte."""
    scratch = Path(tempfile.mkdtemp(prefix='schemaxis-exiftool-'))
    try:
        (scratch / CAPTURED).mkdir()
        (scratch / STAGE).mkdir()
        (scratch / captured_file(item['id'], ext_of(item))).write_bytes(data)
        stage = write_stage(item['id'])
        try:
            run_stage(scratch, stage, stage_command(executable, stage, [], item['args'], item['id'], ext_of(item)), [captured_file(item['id'], ext_of(item))], remaining_timeout(wb.VERIFY_TIMEOUT))
        except SchemaxisError as error:
            fail('VERIFICATION_FAILED', 'the fresh native write of the retained capture failed (' + error.fault.code + ')', stage)
        if (scratch / stage_file(item['id'], ext_of(item))).read_bytes() != produced:
            fail('VERIFICATION_FAILED', 'the fresh native write of the retained capture differs from the retained output', stage)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


def verify(directory, require_result=True, *, executable=None):
    """Recompute every proof from the retained bytes, rebuild every publication, and replay the native listings and writes with a trusted runtime."""
    directory = Path(directory).absolute()
    try:
        with execution_deadline(wb.VERIFY_TIMEOUT):
            p = plan(legacy.read(directory, 'authored.json'))
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
            ctx = e3write.Context(p, directory, captured) if p['operation'] in e3write.OPERATIONS else e4copy.Context(p, directory, captured) if p['operation'] in e4copy.OPERATIONS else None
            items = admit(directory, p, captured)
            before_bytes = legacy.bounded(directory / 'before.stdout', limit=listing.MAX_STDOUT + 1)
            if legacy.bounded(directory / 'before.stderr', limit=legacy.LOG_LIMIT):
                fail('VERIFICATION_FAILED', 'the native listing of the captures wrote to stderr', 'before')
            extra_names = e4copy.extra_native_names(p, ctx, items) if p['operation'] in e4copy.OPERATIONS else []
            names_before = [i['file'] for i in items if i['status'] == 'ok'] + extra_names   # the files the retained listing covers, fixed before any plan refuses an item
            before = apply_before(p, items, before_bytes, extra_names)
            for item in items:
                if item['status'] == 'ok':
                    item['beforeRecord'] = before[item['file']]
            plan_items(p, items, before, ctx)
            if p.get('apply') == 'plan':
                return verify_plan_only(directory, p, receipt, captured, items, ctx, before_bytes, names_before, executable, require_result)
            written_ids, failure_ids, stage_data = [], [], {}
            for item in items:
                if item['status'] != 'ok':
                    continue
                ident = item['id']
                published, rejected_path = directory / PHOTOS / (ident + ext_of(item)), directory / REJECTED / (ident + ext_of(item))
                if published.exists() and rejected_path.exists():
                    fail('VERIFICATION_FAILED', 'an item is both published and rejected', ident)
                stage_path = published if published.exists() else rejected_path if rejected_path.exists() else None
                data = legacy.bounded(stage_path, limit=mediaset.item_limit(stage_path)) if stage_path is not None else None
                native = bool(item['args'])
                if native:
                    written_ids.append(ident)
                    if (directory / (write_stage(ident) + '-failure.json')).exists():
                        failure_ids.append(ident)
                item['write'] = {'native': native, 'failure': write_failure(directory, ident, data is not None) if native else None}
                if not native and data != item['bytes_']:
                    fail('VERIFICATION_FAILED', 'an unchanged output differs from its capture', ident)
                stage_data[ident] = (stage_path, data)
            clean = [i for i in items if i['status'] == 'ok' and i['write']['failure'] is None and i['write']['native']]
            after_names = [stage_file(i['id'], ext_of(i)) for i in clean]
            after = {}
            after_bytes = None
            if after_names:
                after_bytes = legacy.bounded(directory / 'after.stdout', limit=listing.MAX_STDOUT + 1)
                if legacy.bounded(directory / 'after.stderr', limit=legacy.LOG_LIMIT):
                    fail('VERIFICATION_FAILED', 'the native listing of the written files wrote to stderr', 'after')
                after = dict(zip(after_names, listing.parse(after_bytes, after_names)))
            elif (directory / 'after-launcher.py').exists():
                fail('VERIFICATION_FAILED', 'an after listing exists although no item was cleanly written', 'after')
            trusted = trusted_runtime(executable)
            fresh_after = None
            if trusted is not None and after_names:
                # a fresh listing of the retained output bytes is used for the proofs, so a changed output surfaces as its exact semantic fault before any replay mismatch
                fresh_after = fresh_listing({stage_file(i['id'], ext_of(i)): stage_data[i['id']][1] for i in clean}, after_names, trusted, 'after')
                if fresh_after != after_bytes:
                    after = dict(zip(after_names, listing.parse(fresh_after, after_names)))
            outcomes = []
            for index, item in enumerate(items):
                if item['status'] != 'ok':
                    outcomes.append(evaluate(p, item, index, None, None, None))
                    continue
                path, data = stage_data[item['id']]
                record = after.get(stage_file(item['id'], ext_of(item))) if item['write']['native'] else item['beforeRecord']
                outcome = evaluate(p, item, index, data, record, item['write']) if (data is not None or item['write']['failure']) else evaluate(p, item, index, b'', None, {'failure': {'code': 'NATIVE_WRITE_FAILED', 'message': 'no output file'}})
                published_here = path is not None and path.parent.name == PHOTOS
                if published_here and outcome['status'] != 'written':
                    fail(outcome['fault']['code'], outcome['fault']['message'], outcome['fault']['location'], item=item['id'], recomputed=outcome['status'], **{k: v for k, v in outcome['fault'].get('observed', {}).items() if k == 'problems'})
                if not published_here and outcome['status'] == 'written':
                    fail('VERIFICATION_FAILED', 'an output that was rejected at run time passes every proof now, so its placement differs from its recomputed proofs', item['id'], recomputed=outcome['status'])
                outcomes.append(outcome)
            if not any(o['status'] == 'written' for o in outcomes):
                fail('VERIFICATION_FAILED', 'a succeeded run has no written item')
            rejected = sorted(i['id'] for i, o in zip(items, outcomes) if i['status'] == 'ok' and o['status'] == 'failed' and stage_data[i['id']][0] is not None)
            files, table = documents(p, captured['rows'], items, outcomes, ctx)
            membership(directory, p, captured, written_ids, rejected, table)
            for name, content in files.items():
                found = legacy.bounded(directory / name, limit=JSON_LIMIT)
                if found != content:
                    exact = e3write.publication_difference(p, name, found, content) if p['operation'] in e3write.OPERATIONS else None
                    if exact:
                        fail(exact[0], exact[1], name)
                    fail('VERIFICATION_FAILED', 'published file differs from independently derived evidence', name)
            for r in table:
                if r['status'] == 'written' and legacy.sha(legacy.bounded(directory / r['output']['file'], limit=mediaset.item_limit(r['output']['file']))) != r['output']['sha256']:
                    fail('VERIFICATION_FAILED', 'a published image differs from its recomputed hash', r['id'])
            retained_executable = receipt['executable']
            if not isinstance(retained_executable, str) or not Path(retained_executable).is_absolute():
                fail('VERIFICATION_FAILED', 'native executable identity must be absolute')
            stage_specs = [('version', [], None), ('libraries', [], None), ('modules', [], None), ('before', names_before, None)] + ([('after', after_names, None)] if after_names else []) + \
                [(write_stage(i['id']), [captured_file(i['id'], ext_of(i))], i) for i in items if i['status'] == 'ok' and i['args']]
            check_stages(directory, retained_executable, stage_specs, failure_ids)
            if receipt['runtime'] != legacy.qualified_runtime(directory, 'VERIFICATION_FAILED'):
                fail('VERIFICATION_FAILED', 'require qualified ExifTool 13.55 runtime identity')
            wb.check_runtime_record(directory, retained_executable)
            if not legacy.same_json(receipt['artifacts'], artifacts(directory, p, table)):
                exact = e3write.slot_difference(receipt['artifacts'], artifacts(directory, p, table)) if p['operation'] in e3write.OPERATIONS else None
                if exact:
                    fail(exact[0], exact[1], 'artifacts')
                fail('VERIFICATION_FAILED', 'publication membership/digest differs')
            wanted = evidence_names(captured, written_ids, rejected, bool(after_names), failure_ids)
            if set(receipt['evidence']) != wanted:
                fail('VERIFICATION_FAILED', 'native evidence membership differs')
            for n in wanted:
                if digest_of(directory, n, limit_of(n)) != receipt['evidence'][n]:
                    fail('VERIFICATION_FAILED', 'retained native evidence differs', n)
            if trusted is None:
                fail('NATIVE_REPLAY_UNAVAILABLE', 'the native before/after listings and writes cannot be verified without a configured trusted ExifTool 13.55 runtime; the readback and preservation proofs re-derived from the retained bytes are consistent but proof N is not verified', '$.runtime.exiftool',
                     independentVerified=True, nativeVerified=False, recovery='use --exiftool, schemaxis configure exiftool, or SCHEMAXIS_EXIFTOOL (a receipt executable is never launched)')
            same_listing(fresh_listing({n: legacy.bounded(directory / n, limit=mediaset.item_limit(n)) for n in names_before}, names_before, trusted, 'before'), before_bytes, 'before')
            if after_names:
                same_listing(fresh_after, after_bytes, 'after')
            for item in clean:
                replay_write(item, item['bytes_'], trusted, stage_data[item['id']][1])
            manifest = json.loads(files['manifest.json'])
            ok = [r for r in table if r['status'] == 'written']
            fresh = {'verified': True, 'artifacts': len(receipt['artifacts']), 'runtime': RUNTIME, 'operation': p['operation'], 'items': len(table), 'written': len(ok), 'refused': sum(1 for r in table if r['status'] == 'refused'),
                     'failed': sum(1 for r in table if r['status'] == 'failed'), 'setStatus': manifest['status'], 'manifestSha256': legacy.sha(files['manifest.json']), 'publicationSha256': {n: legacy.sha(c) for n, c in sorted(files.items())},
                     'nativeReplay': 'fresh-replay-matched', 'proofs': ['readback', 'preservation', 'nativeDiff'], 'observedMetadataOnly': True, 'privacyCertified': False, 'humanReviewRequired': True}
            if require_result:
                retained = read_json(directory, 'result.json')
                if not legacy.same_json({k: v for k, v in retained.items() if k != 'nativeReplay'}, {**{k: v for k, v in fresh.items() if k != 'nativeReplay'}, 'status': 'succeeded'}):
                    fail('VERIFICATION_FAILED', 'retained result differs from independent reopening')
            return fresh
    except SchemaxisError as error:
        if error.fault.code in ('VERIFICATION_FAILED', 'INCOMPLETE_EXECUTION', 'NATIVE_REPLAY_UNAVAILABLE', 'RUNNER_CANCELLED', 'RUNNER_TIMED_OUT'):
            raise
        fail('VERIFICATION_FAILED', 'retained evidence violates its contract (' + error.fault.code + ': ' + error.fault.message + ')', error.fault.location, cause=error.fault.to_dict())
    except (OSError, ValueError, KeyError, TypeError, IndexError, AttributeError, UnicodeDecodeError, RecursionError) as error:
        fail('VERIFICATION_FAILED', 'invalid retained evidence: ' + str(error))


def stage_path_of(directory, name):
    """Retained bytes of a ``stage/<file>`` input: the file now lives in ``photos/`` or ``rejected/`` under the same name."""
    for sub in (PHOTOS, REJECTED):
        if (directory / sub / Path(name).name).is_file():
            return '%s/%s' % (sub, Path(name).name)
    return name


def check_stages(directory, retained_executable, stage_specs, failure_ids):
    """Every retained native stage was launched by the trusted launcher with the exact command, finished cleanly and read exactly the bytes it names."""
    for stage, names, item in stage_specs:
        failed_stage = item is not None and item['id'] in failure_ids
        command = stage_command(retained_executable, stage, names, item['args'] if item else (), item['id'] if item else None, ext_of(item) if item else '.jpg')
        path = directory / (stage + '-launcher.py')
        if not failed_stage:
            submission = read_json(directory, stage + '-submission.json')
            interpreter = submission.get('interpreter', {}).get('executable') if isinstance(submission, dict) and isinstance(submission.get('interpreter'), dict) else None
            if not isinstance(interpreter, str) or not Path(interpreter).is_absolute() or submission.get('nativeCommand') != [interpreter, str(path)] or type(submission.get('exitCode')) is not int or submission['exitCode'] != 0:
                fail('VERIFICATION_FAILED', 'native command/completion differs', stage)
        if legacy.bounded(path).decode() != launcher(stage, command, names):
            fail('VERIFICATION_FAILED', 'trusted native launcher differs', stage)
        if not legacy.same_json(read_json(directory, stage + '-inputs.json'), {'files': {n: digest_of(directory, n if not n.startswith(STAGE + '/') else stage_path_of(directory, n), limit_of(n)) for n in names}}):
            fail('VERIFICATION_FAILED', 'native input binding differs', stage)


def verify_plan_only(directory, p, receipt, captured, items, ctx, before_bytes, names_before, executable, require_result):
    """Offline verification of an ``apply: plan`` run: the plan is recomputed from the retained captures, inputs and native listing; nothing was written."""
    outcomes = planned_outcomes(items)
    files, table = documents(p, captured['rows'], items, outcomes, ctx)
    membership(directory, p, captured, [], [], table)
    for name, content in files.items():
        found = legacy.bounded(directory / name, limit=JSON_LIMIT)
        if found != content:
            exact = e3write.publication_difference(p, name, found, content) if p['operation'] in e3write.OPERATIONS else None
            if exact:
                fail(exact[0], exact[1], name)          # the same exact code as in a write run (an edited plan is PLAN_INCONSISTENT)
            fail('VERIFICATION_FAILED', 'published file differs from independently derived evidence', name)
    retained_executable = receipt['executable']
    if not isinstance(retained_executable, str) or not Path(retained_executable).is_absolute():
        fail('VERIFICATION_FAILED', 'native executable identity must be absolute')
    if (directory / 'after-launcher.py').exists() or (directory / PHOTOS).exists() and any((directory / PHOTOS).iterdir()):
        fail('VERIFICATION_FAILED', 'a plan-only run holds a written file or an after listing')
    check_stages(directory, retained_executable, [('version', [], None), ('libraries', [], None), ('modules', [], None), ('before', names_before, None)], [])
    if receipt['runtime'] != legacy.qualified_runtime(directory, 'VERIFICATION_FAILED'):
        fail('VERIFICATION_FAILED', 'require qualified ExifTool 13.55 runtime identity')
    wb.check_runtime_record(directory, retained_executable)
    if not legacy.same_json(receipt['artifacts'], artifacts(directory, p, table)):
        fail('VERIFICATION_FAILED', 'publication membership/digest differs')
    wanted = evidence_names(captured, [], [], False, ())
    if set(receipt['evidence']) != wanted:
        fail('VERIFICATION_FAILED', 'native evidence membership differs')
    for n in wanted:
        if digest_of(directory, n, limit_of(n)) != receipt['evidence'][n]:
            fail('VERIFICATION_FAILED', 'retained native evidence differs', n)
    trusted = trusted_runtime(executable)
    if trusted is None:
        fail('NATIVE_REPLAY_UNAVAILABLE', 'the native listing of the captures cannot be verified without a configured trusted ExifTool 13.55 runtime; the plan re-derived from the retained bytes is consistent but the listing is not verified', '$.runtime.exiftool',
             independentVerified=True, nativeVerified=False, recovery='use --exiftool, schemaxis configure exiftool, or SCHEMAXIS_EXIFTOOL (a receipt executable is never launched)')
    same_listing(fresh_listing({n: legacy.bounded(directory / n, limit=mediaset.item_limit(n)) for n in names_before}, names_before, trusted, 'before'), before_bytes, 'before')
    manifest = json.loads(files['manifest.json'])
    fresh = {'verified': True, 'artifacts': len(receipt['artifacts']), 'runtime': RUNTIME, 'operation': p['operation'], 'apply': 'plan', 'items': len(table), 'planned': sum(1 for r in table if r['status'] == 'planned'),
             'refused': sum(1 for r in table if r['status'] == 'refused'), 'written': 0, 'setStatus': manifest['status'], 'manifestSha256': legacy.sha(files['manifest.json']),
             'publicationSha256': {n: legacy.sha(c) for n, c in sorted(files.items())}, 'nativeReplay': 'fresh-replay-matched', 'proofs': ['plan'], 'observedMetadataOnly': True, 'privacyCertified': False, 'humanReviewRequired': True}
    if require_result:
        retained = read_json(directory, 'result.json')
        if not legacy.same_json({k: v for k, v in retained.items() if k != 'nativeReplay'}, {**{k: v for k, v in fresh.items() if k != 'nativeReplay'}, 'status': 'succeeded'}):
            fail('VERIFICATION_FAILED', 'retained result differs from independent reopening')
    return fresh
