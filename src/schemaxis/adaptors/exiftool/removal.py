"""Concrete removal categories for ``removeMetadata``: independent selectors, native deletions derived from the trusted listing, absence proof.

A category is data (``writes.json``): the EXIF tags, XMP properties, IPTC datasets, Photoshop resources and comment segments it names, plus the
native names that delete them. Native deletions are never authored: block deletes name a whole family-1 group, and every other deletion is the
group-qualified name of a key the trusted ExifTool listing of the capture actually reports, validated against a strict pattern. Absence is
then proved twice and separately: the independent readers must find none of the selectors in the output, and a fresh native listing must
report no key the category's native predicate matches. What stays is reported exactly in the residual inventory: this is removal for the listed
categories in the understood locations, never anonymisation, privacy certification or a claim about pixels, file names, unknown maker notes
or embedded content.
"""
import re
import struct

from schemaxis.adaptors.exiftool import edits, iptc as iptc_reader, proofs, tiff, writes

NATIVE_NAME = re.compile(r'[A-Za-z0-9]+(-[A-Za-z0-9]+)?:[A-Za-z0-9-]+')
BLOCK_GROUP = {'GPS:all': 'GPS', 'IFD1:all': 'IFD1', 'MakerNotes:all': 'MakerNotes', 'XMP-iptcExt:all': 'XMP-iptcExt'}
MINIMISE = 'minimise'
IPTC_EXT = 'iptcExt:'
IPTC_EXT_URI = '{http://iptc.org/std/Iptc4xmpExt/2008-02-12/}'


def selectors(categories):
    """The union of the independent selectors of the chosen categories, in catalogue order."""
    cats = writes.categories()
    union = {'exifIfds': [], 'exif': [], 'xmp': [], 'xmpNamespaces': {}, 'iptc': [], 'psir': [], 'comment': False, 'makerNote': False, 'observed': {}, 'blocks': []}
    for name in categories:
        cat = cats[name]
        union['exifIfds'] += [x for x in cat['exifIfds'] if x not in union['exifIfds']]
        union['exif'] += [x for x in cat['exif'] if x not in union['exif']]
        for e in cat['exif']:
            union['observed'].setdefault(e['ifd'], [])
            if e['name'] not in union['observed'][e['ifd']]:
                union['observed'][e['ifd']].append(e['name'])
        union['xmp'] += [x for x in cat['xmp'] if x not in union['xmp']]
        for ns, allowed in cat['xmpNamespaces'].items():
            union['xmpNamespaces'][ns] = sorted(set(union['xmpNamespaces'].get(ns, [])) | set(allowed))
        union['iptc'] += [x for x in cat['iptc'] if x not in union['iptc']]
        union['psir'] += [x for x in cat['psir'] if x not in union['psir']]
        union['comment'] = union['comment'] or cat['comment']
        union['makerNote'] = union['makerNote'] or bool(cat.get('makerNote'))
        for group in cat['native']['observed']:
            union['observed'].setdefault(group['group1'], [])
            union['observed'][group['group1']] += [n for n in group['names'] if n not in union['observed'][group['group1']]]
        union['blocks'] += [b for b in cat['native']['blocks'] if b not in union['blocks']]
    return union


def local_name(name):
    """The local part of a canonical ``prefix:Name`` or an expanded ``{uri}Name`` property name."""
    return name.rpartition('}')[2] if name.startswith('{') else name.partition(':')[2]


def xmp_present(payloads, patterns):
    state = payloads.xmp
    if state[0] != 'ok':
        return []
    return sorted(name for name in state[1] if any(writes.xmp_match(p, name) for p in patterns))


def xmp_namespace_present(payloads, namespace):
    state = payloads.xmp
    if state[0] != 'ok':
        return []
    return sorted(name for name in state[1] if name.startswith(namespace + ':') or (namespace == 'iptcExt' and name.startswith(IPTC_EXT_URI)))


def inventory(sel, item):
    """What the selectors find in one parsed file: ``{'exif': [...], 'ifds': [...], 'xmp': [...], 'iptc': [...], 'psir': [...], 'comment': n, 'makerNote': bool}``."""
    payloads, walk = item['payloads'], item['walk']
    found = {'exif': [], 'ifds': [], 'xmp': [], 'xmpNamespaces': {}, 'iptc': [], 'psir': [], 'comment': 0, 'makerNote': False}
    if payloads.exif[0] == 'ok':
        ifds = payloads.exif[1]['ifds']
        for ifd in sel['exifIfds']:
            if ifd in ifds:
                found['ifds'].append(ifd)
        for e in sel['exif']:
            group = ifds.get(e['ifd'])
            if group and group[0] == 'ok' and any(x.tag == int(e['tag'], 16) for x in group[1]):
                found['exif'].append('%s:%s' % (e['ifd'], e['tag']))
        group = ifds.get('ExifIFD')
        found['makerNote'] = bool(sel.get('makerNote') and group and group[0] == 'ok' and any(x.tag == 0x927C for x in group[1]))
    found['xmp'] = xmp_present(payloads, sel['xmp'])
    for ns in sel['xmpNamespaces']:
        found['xmpNamespaces'][ns] = xmp_namespace_present(payloads, ns)
    if payloads.iptc[0] == 'ok':
        sets = payloads.iptc[1]['datasets']
        found['iptc'] = ['%d:%d' % (i['record'], i['dataset']) for i in sel['iptc'] if (i['record'], i['dataset']) in sets]
    if walk is None:
        resources = {}
        for body in item['located']['iptc']:
            try:
                resources.update(dict(iptc_reader.resources(body)))
            except iptc_reader.Problem:
                pass
    else:
        resources = proofs.iim_resources(walk, item['bytes_'])
    found['psir'] = [i for i in sel['psir'] if i in resources]
    found['comment'] = sum(1 for s in walk['pre'] if s['marker'] == 0xFE) if sel['comment'] and walk is not None else 0
    return found


def plan_item(categories, item, before):
    """The removal plan of one item from its independent inventory and native before listing; a ``Refusal`` when a removal cannot be established."""
    if before is None:
        raise edits.Refusal('REMOVAL_NEEDS_LISTING', 'the native listing of the capture is required to name the native deletions')
    container = item.get('container', 'jpeg')
    if container != 'jpeg':
        container_guard(container, categories)
    if list(categories) == [MINIMISE]:
        return plan_minimise(item, before)
    sel = selectors(categories)
    payloads = item['payloads']
    found = inventory(sel, item)
    if container != 'jpeg':
        found['makerNote'] = False         # a maker note is kept (never deleted outside JPEG): published as the residual makerNoteMayIdentifyDevice
    for family, state in (('exif', payloads.exif), ('xmp', payloads.xmp), ('iptc', payloads.iptc)):
        if state[0] == 'error':
            raise edits.Refusal('REMOVAL_UNREADABLE', 'the %s payload cannot be read, so absence of the selected metadata could not be proved' % family.upper(), '$.categories', family=family, cause=state[2])
    if payloads.iptc[0] == 'ok' and payloads.iptc[1]['charset'] == 'unsupported' and not sel['iptc']:
        pass
    blocks, observed, notes = [], [], []
    if 'GPS' in found['ifds'] and 'GPS:all' in sel['blocks']:
        blocks.append('GPS:all')
    if 'IFD1' in found['ifds'] and 'IFD1:all' in sel['blocks']:
        blocks.append('IFD1:all')
    native_groups = {(o['group0'], o['group1']) for o in before['observations']}
    if found['makerNote']:
        if not any(g0 == 'MakerNotes' for g0, _ in native_groups):
            raise edits.Refusal('MAKERNOTE_UNDELETABLE', 'the file holds a maker note that ExifTool does not recognise, so ExifTool cannot remove it and its absence cannot be proved', '$.categories', note='opaque ExifIFD 0x927C')
        blocks.append('MakerNotes:all')
    for ns, allowed in sel['xmpNamespaces'].items():
        names = found['xmpNamespaces'][ns]
        if names:
            extra = [n for n in names if local_name(n) not in allowed]
            if extra:
                raise edits.Refusal('REMOVAL_UNDELETABLE', 'ExifTool cannot delete these XMP structures one by one; deleting the whole %s namespace would also remove properties outside the selected categories' % ns, '$.categories', namespace=ns, others=[e[:60] for e in extra][:8])
            blocks.append('XMP-%s:all' % ns)
    named = {(o['group1'], o['name']) for o in before['observations']}
    for e in sel['exif']:
        if '%s:%s' % (e['ifd'], e['tag']) in found['exif'] and (e['ifd'], e['name']) not in named:
            raise edits.Refusal('REMOVAL_NATIVE_NAME_UNKNOWN', 'ExifTool does not list a tag the independent reader found, so it cannot be named for deletion', '$.categories', tag='%s:%s' % (e['ifd'], e['tag']), expected=e['name'])
    seen = set()
    for o in before['observations']:
        patterns = sel['observed'].get(o['group1'])
        if patterns and any(writes.native_match(p, o['name']) for p in patterns):
            name = '%s:%s' % (o['group1'], o['name'])
            if name not in seen:
                if not NATIVE_NAME.fullmatch(name):
                    raise edits.Refusal('REMOVAL_NATIVE_NAME_INVALID', 'a native key name is not a plain group-qualified name', '$.categories', name=name[:60])
                seen.add(name)
                observed.append(name)
    if container == 'webp':
        predict_webp_layout(item, webp_deleted_chunks(item, exif_removed=exif_fully_selected(payloads, found), xmp_removed=xmp_fully_selected(payloads, found)))
    iptc_present = bool(found['iptc'])
    psir_present = bool(found['psir'])
    comment = found['comment'] > 0
    present = bool(found['ifds'] or found['exif'] or found['xmp'] or any(found['xmpNamespaces'].values()) or iptc_present or psir_present or comment or found['makerNote'])
    xmp_after = payloads.xmp[0] != 'absent'
    digest = bool(iptc_present and (xmp_after or edits_digest_present(item)))
    plan = {'categories': list(categories), 'found': found, 'blocks': blocks, 'observed': observed, 'present': present, 'notes': notes,
            'iptc': {'changed': iptc_present, 'assignCharset': False, 'digest': digest, 'created': False},
            'declared': {'exif': bool(found['ifds'] or found['exif'] or found['makerNote']), 'xmp': bool(found['xmp'] or any(found['xmpNamespaces'].values())), 'iptc': iptc_present or psir_present,
                         'comment': comment, 'thumbnail': 'IFD1' in found['ifds']},
            'xmpWritten': bool(found['xmp'] or any(found['xmpNamespaces'].values())), 'selectors': {k: sel[k] for k in ('exifIfds', 'exif', 'xmp', 'iptc', 'psir', 'comment')}}
    return plan


def container_guard(container, categories):
    """The registry's removal rules of a non-JPEG container: HEIF is refused, minimise and thumbnails only where the profile offers them."""
    from schemaxis.adaptors.exiftool import e5profiles
    rules = e5profiles.profile(container)['removal']
    if 'unsupportedCode' in rules:
        raise edits.Refusal(rules['unsupportedCode'], 'removal is not offered for %s files: %s' % (container.upper(), rules['reason']), '$.categories', container=container, limitation='heifRemovalUnsupported')
    minimise = e5profiles.profile(container)['minimise']
    if list(categories) == [MINIMISE] and not minimise['supported']:
        raise edits.Refusal(minimise['code'], 'minimise is not offered for %s files: %s' % (container.upper(), minimise['reason']), '$.categories', container=container)
    unavailable = [c for c in categories if c != MINIMISE and c not in rules['categories']]
    if unavailable:
        reason = rules.get('thumbnails', {}).get('reason', 'the registry does not list it') if unavailable[0] == 'thumbnails' else 'the registry does not list it'
        raise edits.Refusal('REMOVAL_CATEGORY_UNSUPPORTED_IN_CONTAINER', 'the category %s is not offered for %s files (%s)' % (unavailable[0], container.upper(), reason), '$.categories', container=container, category=unavailable[0])


def edits_digest_present(item):
    if item['walk'] is None:
        from schemaxis.adaptors.exiftool import e5edit
        return e5edit.digest_present(item['located'])
    return 0x0425 in proofs.iim_resources(item['walk'], item['bytes_'])


def assignments(plan):
    """Native arguments: whole-group deletes and the observed group-qualified deletes, then the IPTC digest refresh when IPTC datasets went."""
    if 'minimise' in plan:
        return minimise_assignments(plan)
    args = ['-%s=' % b for b in plan['blocks']] + ['-%s=' % name for name in plan['observed']]
    if plan['iptc']['digest']:
        args.append('-Photoshop:IPTCDigest=new')
    if not (plan['blocks'] or plan['observed']):
        return []
    return args


def native_targets(plan):
    """``(qualified keys, group1 prefixes, group0 set)`` of everything the plan deletes, for the native diff."""
    groups = {BLOCK_GROUP[b] for b in plan['blocks'] if b in BLOCK_GROUP}
    return set(plan['observed']), groups


def residual_check(plan, payloads, walk, at, located=None):
    """Independent absence proof: none of the plan's selectors may be found in the output."""
    sel = plan['selectors']
    problems = []
    probe = {'payloads': payloads, 'walk': walk, 'bytes_': b'', 'located': located}
    out = inventory({**sel, 'xmpNamespaces': {ns: [] for ns in plan['found']['xmpNamespaces']}, 'observed': {}, 'blocks': [], 'makerNote': plan['found']['makerNote']}, probe)
    for key, label in (('ifds', 'exifIfd'), ('exif', 'exif'), ('xmp', 'xmp'), ('iptc', 'iptc'), ('psir', 'photoshop')):
        if out[key]:
            problems.append(proofs.problem('REMOVAL_RESIDUAL', 'selected %s metadata is still present in the output' % label, at + '.' + label, remaining=[str(x) for x in out[key]][:12]))
    for ns, names in out['xmpNamespaces'].items():
        if names:
            problems.append(proofs.problem('REMOVAL_RESIDUAL', 'XMP properties of the removed namespace remain', at + '.xmp', remaining=names[:12]))
    if out['comment']:
        problems.append(proofs.problem('REMOVAL_RESIDUAL', 'JPEG comment segments remain', at + '.comment', remaining=out['comment']))
    if plan['found']['makerNote'] and out['makerNote']:
        problems.append(proofs.problem('REMOVAL_RESIDUAL', 'the maker note remains', at + '.makerNote'))
    return problems


def native_residual(plan, after_record, at):
    """A fresh listing of the output must report no key the categories' native predicates match, and no key of a removed block group."""
    sel = selectors(plan['categories'])
    problems = []
    groups = {BLOCK_GROUP[b] for b in sel['blocks'] if b in BLOCK_GROUP} | ({'XMP-iptcExt'} if sel['xmpNamespaces'] else set())
    for o in after_record['observations']:
        hit = o['group1'] in groups and not (o['group1'] == 'MakerNotes') or (o['group0'] == 'MakerNotes' and 'MakerNotes:all' in sel['blocks'])
        hit = hit or any(writes.native_match(p, o['name']) for p in sel['observed'].get(o['group1'], []))
        if hit:
            problems.append(proofs.problem('REMOVAL_RESIDUAL', 'a fresh native listing of the output still reports a selected key', at + '.native', key='%s:%s' % (o['group1'], o['name'])))
    return problems[:12]


# ---------------------------------------------------------------- minimise: rendering-preserving minimisation
# A closed list of known deletions (never a bare delete-all): whole EXIF, XMP, IPTC and Photoshop blocks and the JPEG comments go; the encoded image
# and the JFIF, Adobe and ICC segments are not touched; the few EXIF values that decide how the picture is drawn are read independently from the
# capture and assigned back numerically. ExifTool then rebuilds a small EXIF block and adds a closed set of mandatory values, which are declared
# value-aware side effects (proved in the output and in the native diff), never ignored.
ALLOWED_IFD0 = {0x0112, 0x0213, 0x011A, 0x011B, 0x0128, 0x8769}
ALLOWED_EXIF_IFD = {0xA001, 0x9000, 0x9101, 0xA005}
MIN_GROUP0 = ('EXIF', 'XMP', 'IPTC', 'Photoshop', 'MakerNotes')
COMPONENTS = bytes([1, 2, 3, 0])
BYTE_ORDER = {'<': 'Little-endian', '>': 'Big-endian'}


def jfif_of(walk):
    """``(units, xDensity, yDensity)`` of the JFIF segment, or ``None`` (a container has none)."""
    for s in (walk['pre'] if walk is not None else ()):
        body = s['body']
        if s['marker'] == 0xE0 and body[:5] == b'JFIF\0' and len(body) >= 12:
            return body[7], struct.unpack('>H', body[8:10])[0], struct.unpack('>H', body[10:12])[0]
    return None


def exif_entries(payloads, ifd):
    state = payloads.exif
    if state[0] != 'ok':
        return []
    group = state[1]['ifds'].get(ifd)
    return group[1] if group and group[0] == 'ok' else []


def interop_index(located):
    """The InteropIndex string of the Exif payload (``None`` when there is no readable Interop IFD)."""
    if not located['exif']:
        return None
    payload = located['exif'][0]
    try:
        walked = tiff.walk(payload)
        group = walked['ifds'].get('ExifIFD')
        pointer = next((e for e in group[1] if e.tag == 0xA005), None) if group and group[0] == 'ok' else None
        if pointer is None or pointer.kind != 4 or pointer.count != 1:
            return None
        entries, _ = tiff.read_ifd(payload, struct.unpack(walked['order'] + 'I', pointer.raw)[0], walked['order'], [0])
    except (tiff.Damaged, struct.error, TypeError):
        return None
    found = [e for e in entries if e.tag == 0x0001]
    return found[0].raw.rstrip(b'\0').decode('ascii', 'replace') if len(found) == 1 and found[0].kind == 2 and found[0].raw else None


def xmp_values(payloads, name):
    state = payloads.xmp
    if state[0] != 'ok':
        return []
    return [o.get('value') if o.get('kind') == 'text' else None for o in state[1].get(name, [])]


def preserved_values(item):
    """``{name: value}`` of the rendering values kept by minimise, read independently from the capture; a ``Refusal`` when one cannot be kept faithfully."""
    mini, payloads = writes.minimise(), item['payloads']
    kept = {}
    for e in mini['preserve']:
        if e['ifd'] == 'InteropIFD':
            value = interop_index(item['located'])
            present = any(x.tag == 0xA005 for x in exif_entries(payloads, 'ExifIFD'))
            if present and value not in e['values']:
                raise edits.Refusal('MINIMISE_RENDERING_UNPRESERVED', 'the Exif Interop record cannot be kept faithfully, so the capture is not minimised', '$.categories', tag='InteropIndex', value=(value or '')[:16])
            if value is not None:
                kept[e['name']] = value
            continue
        found = [x for x in exif_entries(payloads, e['ifd']) if x.tag == int(e['tag'], 16)]
        if not found:
            continue
        values = found[0].values() if len(found) == 1 else None
        if values is None or len(values) != 1 or values[0] not in e['values']:
            raise edits.Refusal('MINIMISE_RENDERING_UNPRESERVED', 'the capture holds a %s that is repeated or outside the understood values, so it cannot be kept faithfully' % e['name'], '$.categories', tag=e['name'])
        kept[e['name']] = values[0]
    for e in mini['refuseIfPresent']:
        if any(x.tag == int(e['tag'], 16) for x in exif_entries(payloads, e['ifd'])):
            raise edits.Refusal('MINIMISE_RENDERING_UNPRESERVED', e['reason'], '$.categories', tag=e['name'])
    for prop, where in mini['xmpRendering'].items():
        texts = xmp_values(payloads, prop)
        if not texts:
            continue
        mirror = next(e for e in mini['preserve'] if (e['ifd'], e['tag']) == (where['ifd'], where['tag']))
        if mirror['name'] not in kept or any(t is None or t.strip() != str(kept[mirror['name']]) for t in texts):
            raise edits.Refusal('RENDERING_REPRESENTATION_CONFLICT', 'XMP %s is not the same as the EXIF value, and the XMP block would be deleted, which could change how some viewers draw the picture' % prop, '$.categories', property=prop, exif=kept.get(mirror['name']))
    return kept


def expected_resolution(walk):
    jfif = jfif_of(walk)
    return None if jfif is None else {'x': jfif[1], 'y': jfif[2], 'unit': jfif[0] + 1}


def exif_state_problems(payloads, located, walk, kept):
    """What stands in the Exif block that is not the closed minimal state (an empty list means the block is exactly the preserved values plus the declared mandatory ones)."""
    state = payloads.exif
    if state[0] == 'absent':
        return [] if not kept else ['preserved values are missing: ' + ','.join(sorted(kept))]
    if state[0] != 'ok':
        return ['unreadable']
    problems = []
    ifds = state[1]['ifds']
    for name in sorted(set(ifds) - {'IFD0', 'ExifIFD'}):
        problems.append('ifd:' + name)
    resolution = expected_resolution(walk)
    for ifd, allowed in (('IFD0', ALLOWED_IFD0), ('ExifIFD', ALLOWED_EXIF_IFD)):
        for e in exif_entries(payloads, ifd):
            tag = '%s:0x%04X' % (ifd, e.tag)
            if e.tag not in allowed:
                problems.append(tag)
                continue
            values = e.values()
            if ifd == 'IFD0' and e.tag == 0x0112 and (kept.get('Orientation'), ) != (values[0] if values and len(values) == 1 else None,):
                problems.append(tag + ' value')
            if ifd == 'IFD0' and e.tag == 0x0213 and (values != [kept.get('YCbCrPositioning', 1)]):
                problems.append(tag + ' value')
            if ifd == 'IFD0' and e.tag in (0x011A, 0x011B):
                want = None if resolution is None else resolution['x' if e.tag == 0x011A else 'y']
                if resolution is None or not values or len(values) != 1 or not isinstance(values[0], tuple) or values[0][1] == 0 or values[0][0] != want * values[0][1]:
                    problems.append(tag + ' value')
            if ifd == 'IFD0' and e.tag == 0x0128 and (resolution is None or values != [resolution['unit']]):
                problems.append(tag + ' value')
            if ifd == 'ExifIFD' and e.tag == 0xA001 and (values != [kept.get('ColorSpace')]):
                problems.append(tag + ' value')
            if ifd == 'ExifIFD' and e.tag == 0x9000 and e.raw != b'0232':
                problems.append(tag + ' value')
            if ifd == 'ExifIFD' and e.tag == 0x9101 and e.raw != COMPONENTS:
                problems.append(tag + ' value')
    index = interop_index(located)
    has_pointer = any(x.tag == 0xA005 for x in exif_entries(payloads, 'ExifIFD'))
    if has_pointer != ('InteropIndex' in kept) or (has_pointer and index != kept.get('InteropIndex')):
        problems.append('InteropIFD')
    return problems


def plan_minimise(item, before):
    """The minimise plan of one item: closed deletions, the independently read rendering values to keep, and the byte order to keep."""
    payloads, walk = item['payloads'], item['walk']
    for family, state in (('exif', payloads.exif), ('xmp', payloads.xmp), ('iptc', payloads.iptc)):
        if state[0] == 'error':
            raise edits.Refusal('REMOVAL_UNREADABLE', 'the %s payload cannot be read, so its minimisation could not be proved' % family.upper(), '$.categories', family=family, cause=state[2])
        if state[0] == 'ambiguous':
            raise edits.Refusal('REMOVAL_UNREADABLE', 'the %s payload is repeated, so no single one is authoritative' % family.upper(), '$.categories', family=family, cause=state[1])
    if walk is None:
        return plan_minimise_container(item, before)
    mini = writes.minimise()
    kept = preserved_values(item)
    roles = [s['role'] for s in walk['pre']]
    comments = sum(1 for s in walk['pre'] if s['marker'] == 0xFE)
    exif_present, xmp_present, iptc_present = 'exif' in roles, 'xmp' in roles, 'iptc' in roles
    exif_rewrite = exif_present and bool(exif_state_problems(payloads, item['located'], walk, kept))
    sel = selectors(list(writes.categories()))
    found = inventory(sel, item)
    blocks = [b for b, wanted in (('EXIF:all', exif_rewrite), ('XMP:all', xmp_present), ('IPTC:all', iptc_present), ('Photoshop:all', iptc_present)) if wanted]
    observed = ['File:Comment'] if comments else []
    order = BYTE_ORDER[payloads.exif[1]['order']] if exif_rewrite and kept and payloads.exif[0] == 'ok' else None
    preserved_args = []
    if exif_rewrite and kept:
        for e in mini['preserve']:
            if e['name'] in kept:
                preserved_args.append('-%s%s=%s' % (e['write'], '#' if e['numeric'] else '', kept[e['name']]))
    plan = {'categories': [MINIMISE], 'found': found, 'blocks': blocks, 'observed': observed, 'present': bool(blocks or observed), 'notes': [],
            'iptc': {'changed': iptc_present, 'assignCharset': False, 'digest': False, 'created': False},
            'declared': {'exif': exif_rewrite, 'xmp': xmp_present, 'iptc': iptc_present, 'comment': comments > 0, 'thumbnail': any(i == 'IFD1' for i in payloads.exif[1]['ifds']) if payloads.exif[0] == 'ok' and exif_rewrite else False},
            'xmpWritten': False, 'selectors': {},
            'minimise': {'preserved': kept, 'byteOrder': order, 'exifRewritten': exif_rewrite, 'jfif': jfif_of(walk), 'preservedArguments': preserved_args,
                         'keptSegments': sorted({'0x%02X' % s['marker'] for s in walk['pre'] if s['role'] in ('rendering', 'other') and s['marker'] != 0xFE})}}
    return plan


POINTER_TAGS = (0x8769, 0x8825, 0xA005)


def exif_fully_selected(payloads, found):
    """Whether every value entry of every Exif IFD of the capture is one the selectors found (the native writer then drops the whole Exif block)."""
    if payloads.exif[0] != 'ok':
        return False
    selected = set(found['exif'])
    for ifd, group in payloads.exif[1]['ifds'].items():
        if group[0] != 'ok':
            return False
        if ifd in found['ifds']:
            continue
        for e in group[1]:
            if e.tag not in POINTER_TAGS and not any(x.partition(':')[0] == ifd and int(x.partition(':')[2], 16) == e.tag for x in selected):
                return False
    return True


def xmp_fully_selected(payloads, found):
    """Whether every XMP property of the capture is one the selectors found."""
    if payloads.xmp[0] != 'ok':
        return False
    covered = set(found['xmp'])
    for names in found['xmpNamespaces'].values():
        covered |= set(names)
    return all(name in covered for name in payloads.xmp[1])


def png_text_rows(located):
    """``[(chunk type, keyword)]`` of every tEXt, zTXt and iTXt chunk of a located PNG other than the XMP carrier, in file order."""
    rows = []
    for r in located['protected']:
        if r[0] == 'png/text':
            kind, _, rest = r[1].partition(':')
            rows.append((kind, rest.rpartition('#')[0]))
    return rows


def webp_deleted_chunks(item, *, exif_removed, xmp_removed):
    """The metadata chunk ids a WebP plan removes entirely (the input of the AM-16R VP8X prediction)."""
    return tuple(i for i, gone in ((b'EXIF', exif_removed), (b'XMP ', xmp_removed)) if gone)


def predict_webp_layout(item, delete):
    """AM-16R at plan time: a layout whose VP8X ExifTool 13.55 would remove or keep inconsistently is refused before any native process; the post-write proof stays authoritative."""
    if item.get('container') != 'webp' or not delete:
        return None
    from schemaxis.adaptors.exiftool import e5riff
    layout = item['located']['layout']
    facts = {'ids': [i.encode('latin-1') for i in layout['ids']], 'vp8x': layout['vp8x'], 'alpha': layout['alpha']}
    found = e5riff.predict_vp8x(facts, delete)
    if not found['admitted']:
        raise edits.Refusal(found['code'], 'ExifTool 13.55 would leave this WebP layout without a consistent VP8X chunk after the removal: ' + found['reason'], '$.categories', container='webp', layout=layout['ids'][:16])
    return found['vp8x']


def plan_minimise_container(item, before):
    """The minimise plan of a PNG or WebP (AM-17 semantics, AM-19 method): the Exif block is reset (``-EXIF:all=``), the XMP block too and every PNG text chunk is deleted by keyword; the rendering values of the E2 keep-set are written back."""
    container, payloads, located = item['container'], item['payloads'], item['located']
    kept = preserved_values(item)
    exif_present, xmp_present = payloads.exif[0] == 'ok', payloads.xmp[0] == 'ok'
    exif_rewrite = exif_present and bool(exif_state_problems(payloads, located, None, kept))
    blocks = [b for b, wanted in (('EXIF:all', exif_rewrite), ('XMP:all', xmp_present)) if wanted]
    observed, text_keys = [], []
    if container == 'png':
        names = {(o['group1'], o['name']) for o in before['observations']}
        for kind, keyword in png_text_rows(located):
            if ('PNG', keyword) not in names:
                raise edits.Refusal('REMOVAL_NATIVE_NAME_UNKNOWN', 'ExifTool does not list a PNG text chunk under its keyword, so it cannot be named for deletion', '$.categories', chunk=kind, keyword=keyword[:40])
            name = 'PNG:' + keyword
            if not NATIVE_NAME.fullmatch(name):
                raise edits.Refusal('REMOVAL_NATIVE_NAME_INVALID', 'a native key name is not a plain group-qualified name', '$.categories', name=name[:60])
            if name not in observed:
                observed.append(name)
                text_keys.append(keyword)
    layout = predict_webp_layout(item, webp_deleted_chunks(item, exif_removed=exif_rewrite and not kept, xmp_removed=xmp_present)) if container == 'webp' else None
    mini = writes.minimise()
    order = BYTE_ORDER[payloads.exif[1]['order']] if exif_rewrite and kept and exif_present else None
    preserved_args = []
    if exif_rewrite and kept:
        preserved_args = ['-%s%s=%s' % (e['write'], '#' if e['numeric'] else '', kept[e['name']]) for e in mini['preserve'] if e['name'] in kept]
    return {'categories': [MINIMISE], 'found': inventory(selectors(list(writes.categories())), item), 'blocks': blocks, 'observed': observed, 'present': bool(blocks or observed), 'notes': [],
            'iptc': {'changed': False, 'assignCharset': False, 'digest': False, 'created': False},
            'declared': {'exif': exif_rewrite, 'xmp': xmp_present, 'iptc': False, 'comment': False, 'thumbnail': False}, 'xmpWritten': False, 'selectors': {},
            'minimise': {'preserved': kept, 'byteOrder': order, 'exifRewritten': exif_rewrite, 'jfif': None, 'preservedArguments': preserved_args, 'keptSegments': [], 'container': container,
                         'textKeywords': text_keys, 'vp8x': layout}}


def minimise_residual_container(plan, payloads, located, at):
    """Independent proof of the closed after-state of a minimised PNG or WebP: no XMP, no text chunk, and an Exif block that is exactly the kept rendering values."""
    problems = []
    if payloads.xmp[0] != 'absent':
        problems.append(proofs.problem('REMOVAL_RESIDUAL', 'an XMP block remains in the minimised output', at + '.xmp'))
    left_text = png_text_rows(located) if located['container'] == 'png' else []
    if left_text:
        problems.append(proofs.problem('REMOVAL_RESIDUAL', 'PNG text chunks remain in the minimised output', at + '.text', keywords=[k[:40] for _, k in left_text][:8]))
    left = exif_state_problems(payloads, located, None, plan['minimise']['preserved'])
    if left:
        code = 'MINIMISE_PRESERVED_CHANGED' if any(x.endswith(' value') or x.startswith('preserved') or x == 'InteropIFD' for x in left) else 'REMOVAL_RESIDUAL'
        problems.append(proofs.problem(code, 'the Exif block of the output is not the closed minimal state', at + '.exif', unexpected=left[:12]))
    return problems


def minimise_assignments(plan):
    mini = plan['minimise']
    args = ['-%s=' % b for b in plan['blocks']] + ['-%s=' % name for name in plan['observed']]
    if mini['byteOrder']:
        args.append('-ExifByteOrder=' + mini['byteOrder'])
    return args + mini['preservedArguments'] if args else []


def minimise_residual(plan, payloads, walk, located, at):
    """Independent proof of the closed after-state of a minimised output."""
    problems = []
    roles = [s['role'] for s in walk['pre']]
    mini = plan['minimise']
    for role, label in (('xmp', 'XMP'), ('iptc', 'Photoshop and IPTC')):
        if role in roles:
            problems.append(proofs.problem('REMOVAL_RESIDUAL', 'a %s block remains in the minimised output' % label, at + '.' + role))
    if any(s['marker'] == 0xFE for s in walk['pre']):
        problems.append(proofs.problem('REMOVAL_RESIDUAL', 'JPEG comment segments remain in the minimised output', at + '.comment'))
    left = exif_state_problems(payloads, located, walk, mini['preserved'])
    if left:
        code = 'MINIMISE_PRESERVED_CHANGED' if any(x.endswith(' value') or x.startswith('preserved') or x == 'InteropIFD' for x in left) else 'REMOVAL_RESIDUAL'
        problems.append(proofs.problem(code, 'the Exif block of the output is not the closed minimal state', at + '.exif', unexpected=left[:12]))
    return problems


REGENERATED = {('IFD0', 'XResolution'), ('IFD0', 'YResolution'), ('IFD0', 'ResolutionUnit'), ('IFD0', 'YCbCrPositioning'), ('ExifIFD', 'ExifVersion'), ('ExifIFD', 'ComponentsConfiguration'), ('InteropIFD', 'InteropVersion')}
KEPT_NATIVE = {('IFD0', 'Orientation'), ('IFD0', 'YCbCrPositioning'), ('ExifIFD', 'ColorSpace'), ('InteropIFD', 'InteropIndex')} | REGENERATED


def regenerated_rule(key, values, mini):
    """The id of the declared mandatory value ExifTool writes when it rebuilds the small Exif block, when ``values`` is exactly that value."""
    _, group1, name = key
    jfif = mini['jfif']
    text = [str(v) for v in values]
    if (group1, name) in (('IFD0', 'XResolution'), ('IFD0', 'YResolution')):
        want = None if jfif is None else jfif[1 if name == 'XResolution' else 2]
        return 'S4-exifResolution' if want is not None and len(text) == 1 and float(text[0]) == want else None
    if (group1, name) == ('IFD0', 'ResolutionUnit'):
        return 'S4-exifResolutionUnit' if jfif is not None and text == [str(jfif[0] + 1)] else None
    if (group1, name) == ('IFD0', 'YCbCrPositioning'):
        return 'S4-yCbCrPositioning' if text == [str(mini['preserved'].get('YCbCrPositioning', 1))] else None
    if (group1, name) == ('ExifIFD', 'ExifVersion'):
        return 'S4-exifVersion' if text == ['0232'] else None
    if (group1, name) == ('ExifIFD', 'ComponentsConfiguration'):
        return 'S4-componentsConfiguration' if text == ['1 2 3 0'] else None
    if (group1, name) == ('InteropIFD', 'InteropVersion'):
        return 'S4-interopVersion' if text == ['0100'] else None
    return None


def minimise_diff(before, after, mini, exif_gone, extra=None):
    """Classify the native before/after differences of a minimise: removals in the deleted groups, the closed mandatory values, and nothing else.
    ``extra(key, before, after)`` names a container's closed native side effects (a created or removed VP8X and its flags)."""
    one, two = proofs.native_map(before), proofs.native_map(after)
    text_keys = {('PNG', k) for k in mini.get('textKeywords', ())}
    out = {'targets': [], 'sideEffects': [], 'renumbered': [], 'unexplained': []}
    for key in sorted(set(one) | set(two)):
        a, b = one.get(key), two.get(key)
        if a == b:
            continue
        label = '%s:%s:%s' % key
        if a is not None and b is not None and len(a) > 1 and sorted(map(repr, a)) == sorted(map(repr, b)):
            out['renumbered'].append(label)
            continue
        group0, group1, name = key
        removable = group0 in MIN_GROUP0 or (group1, name) in (('File', 'Comment'), ('File', 'CurrentIPTCDigest')) or ((group1, name) == ('File', 'ExifByteOrder') and exif_gone) or (group1, name) in text_keys
        if a is not None and b is None and removable:
            out['targets'].append(label)
            continue
        rule = regenerated_rule(key, proofs.text_of(b or []), mini) if b is not None and group0 == 'EXIF' else None
        if rule:
            out['sideEffects'].append({'key': label, 'rule': rule})
            continue
        rule = extra(key, list(a or []), list(b or [])) if extra is not None else None
        if rule:
            out['sideEffects'].append({'key': label, 'rule': rule})
            continue
        out['unexplained'].append({'key': label, 'before': proofs.text_of(a or [])[:6], 'after': proofs.text_of(b or [])[:6]})
    return out


def minimise_native_residual(after_record, at, text_keywords=()):
    """A fresh listing of the output may only report the preserved and mandatory Exif keys in the deleted groups (and none of the deleted PNG text keywords)."""
    problems = []
    for o in after_record['observations']:
        if o['group1'] == 'PNG' and o['name'] in text_keywords:
            problems.append(proofs.problem('REMOVAL_RESIDUAL', 'a fresh native listing of the minimised output still reports a deleted PNG text keyword', at + '.native', key='PNG:' + o['name']))
    for o in after_record['observations']:
        if o['group0'] in MIN_GROUP0 and (o['group1'], o['name']) not in KEPT_NATIVE or (o['group1'], o['name']) == ('File', 'Comment'):
            problems.append(proofs.problem('REMOVAL_RESIDUAL', 'a fresh native listing of the minimised output reports a key outside the closed minimal state', at + '.native', key='%s:%s' % (o['group1'], o['name'])))
    return problems[:12]
