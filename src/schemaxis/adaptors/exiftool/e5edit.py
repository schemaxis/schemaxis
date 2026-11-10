"""E5 container hooks of the E2 copy writer (standard library only): admission, plan guards, the allowed-change list of proof P and the closed native side effects.

The writer itself is unchanged: one ExifTool process per item writes a private stage copy of a captured file. This module only answers the container
questions that the JPEG-only writer never had to ask:

* ``admit``: locate the capture by signature and refuse, before any native process, a file whose structure a write cannot protect (the locator's precise
  write refusal, e.g. ``TIFF_UNKNOWN_OFFSET_SUSPECT`` or ``PNG_METADATA_AFTER_IDAT``);
* ``creation_guard``: HEIF metadata items that do not exist are never created (``HEIF_METADATA_ITEM_CREATION_UNSUPPORTED``, a named native capability gap);
* ``empty_item_guard``: a HEIF Exif or XMP item that the plan would leave without any metadata is refused before native (``HEIF_EMPTY_METADATA_ITEM``: 13.55 writes a zero-length extent);
* ``allowed``: which fingerprint rows a plan may change, so proof P (``e5proof.preserve``) is exact;
* ``side_effect``: the closed, value-aware native listing changes that are not plan targets (relocated image extents, a rebuilt HEIF media-data box).

Nothing here decodes pixels.
"""
import hashlib
import re

from schemaxis.adaptors.exiftool import containers, e5locate, e5payloads, edits, iptc as iptc_reader

CREATION_CODE = 'HEIF_METADATA_ITEM_CREATION_UNSUPPORTED'
EMPTY_CODE = 'HEIF_EMPTY_METADATA_ITEM'
POINTER_TAGS = (0x014A, 0x8769, 0x8825, 0xA005)         # sub-IFD pointers: structure of the Exif block, never metadata that keeps an item alive
IFD_PATHS = {'IFD0': 'IFD0', 'ExifIFD': 'IFD0/Exif', 'GPS': 'IFD0/GPS', 'IFD1': 'IFD1', 'InteropIFD': 'IFD0/Exif/Interop'}
TIFF_LIKE = ('tiff', 'dng')
BINARY_SIZE = re.compile(r'\(Binary data \d+ bytes, use -b option to extract\)')


def admit(data, relative=None):
    """The located capture; the first precise write refusal of the locator is raised as ``containers.Refused``."""
    located = e5locate.locate(data, relative)
    refusals = located['write']['refusals'] if located.get('write') else []
    if refusals:
        first = refusals[0]
        raise containers.Refused(first['code'], first['message'], **first.get('observed', {}))
    return located


def digest_present(located):
    """Whether the capture's Photoshop resources hold an IPTC digest (resource 0x0425)."""
    for body in located['iptc']:
        try:
            if any(ident == 0x0425 for ident, _ in iptc_reader.resources(body)):
                return True
        except iptc_reader.Problem:
            continue
    return False


def iim_md5(located):
    """MD5 of the stored IPTC-NAA bytes of a located file (a TIFF's tag 0x83BB as stored, else resource 0x0404), or ``None``."""
    if located.get('iptcStoredMd5'):
        return located['iptcStoredMd5']
    for body in located['iptc']:
        try:
            found = dict(iptc_reader.resources(body)).get(0x0404)
        except iptc_reader.Problem:
            continue
        if found is not None:
            return hashlib.md5(found).hexdigest()
    return None


def creation_guard(container, payloads, plan, at='$.edits'):
    """Refuse a plan that would make the native writer create a metadata item that the capture does not have (HEIF only).

    Native 13.55 creating an Exif or XMP item in a HEIC that has none is not reproducible: over 20 runs per kind 9 or more produced no output and
    every combined Exif+XMP creation produced a wrong file (see the evidence). Editing items that exist is deterministic and is proved normally.
    """
    if container != 'heif':
        return
    missing = [family for family, written in (('xmp', plan['declared']['xmp']), ('exif', plan['declared']['exif'])) if written and getattr(payloads, family)[0] == 'absent']
    if missing:
        raise edits.Refusal(CREATION_CODE, 'this edit would create a %s metadata item that the HEIF file does not have; creating items is a named capability gap of ExifTool 13.55 (not reproducible), so only existing items are edited' % '/'.join(m.upper() for m in missing),
                            at, container='heif', missing=missing, limitation='heifNativeMetadataCreationNotReproducible')


def plan_effects(plan):
    """What a plan writes and deletes in the Exif and XMP slots: ``(xmp_written, xmp_properties_deleted, exif_written, exif_(ifd, tag)_deleted)``.

    Field destinations of an edit (and of the edit part of a transfer) are resolved against the pinned write table; extras carry their own property or IFD and tag; the time and location parts
    of a plan only write. A destination in state ``skip`` changes nothing."""
    xmp_written = exif_written = False
    xmp_deleted, exif_deleted = set(), set()
    e2 = plan if plan.get('kind') == 'edit' else plan.get('edit')
    pairs = []
    if e2:
        by_write = {d['write']: d for name in e2['fields'] for d in edits.writes.fields()[name]['destinations']}
        pairs += [(d, by_write[d['write']]) for f in e2['fields'].values() for d in f['destinations']]
    pairs += [(d, d) for x in plan.get('extras', ()) for d in x['destinations']]
    for state_row, spec in pairs:
        if state_row['state'] not in ('write', 'delete'):
            continue
        if spec['family'] == 'xmp':
            if state_row['state'] == 'write':
                xmp_written = True
            else:
                xmp_deleted.add(spec['property'])
        elif spec['family'] == 'exif':
            if state_row['state'] == 'write':
                exif_written = True
            else:
                exif_deleted.add((spec['ifd'], int(spec['tag'], 16)))
    parts = [plan] if plan.get('kind') in ('time', 'location') else [plan.get('time'), plan.get('location')]
    for part in parts:
        if part:
            xmp_written = xmp_written or bool(part.get('xmpTargets'))
            exif_written = exif_written or bool(part.get('exifTargets'))
    return xmp_written, xmp_deleted, exif_written, exif_deleted


def empty_item_guard(container, payloads, plan, at='$.edits'):
    """Refuse, before any native process, a plan that would leave an existing HEIF Exif or XMP item with no metadata at all (contract 2.4): 13.55 then writes a zero-length extent, which the
    format reads as "to the end of the container", i.e. as the image payload. A plan that writes anything to the item, or that leaves any other property or entry in it, is ordinary and
    unaffected; an item the reader could not fully enumerate is not judged here (the post-write structure check still stands)."""
    if container != 'heif' or plan.get('kind') == 'unchanged':
        return
    xmp_written, xmp_deleted, exif_written, exif_deleted = plan_effects(plan)
    emptied = []
    if payloads.xmp[0] == 'ok' and xmp_deleted and not xmp_written and not set(payloads.xmp[1]) - xmp_deleted:
        emptied.append('xmp')
    if payloads.exif[0] == 'ok' and exif_deleted and not exif_written:
        groups = payloads.exif[1]['ifds']
        if all(state == 'ok' for state, _ in groups.values()):
            kept = {(ifd, e.tag) for ifd, (_, entries) in groups.items() for e in entries if e.tag not in POINTER_TAGS} - exif_deleted
            if not kept:
                emptied.append('exif')
    if emptied:
        raise edits.Refusal(EMPTY_CODE, 'this edit would leave the HEIF %s metadata item with no metadata at all; ExifTool 13.55 then writes a zero-length extent that resolves to the image payload, so the edit is refused (keep or write another value in the item)' % '/'.join(m.upper() for m in emptied),
                            at, container='heif', items=emptied, limitation='heifEmptyMetadataItemNotWritable')


def tiff_iptc_guard(container, plan, digest_before, located=None):
    """TIFF/DNG IPTC: native 13.55 stores the IIM in tag 0x83BB as a zero-padded LONG array, so a digest it writes never equals the digest of the stored bytes and it then warns
    ``IPTCDigest is not current``. The plan therefore never assigns the digest, and a capture that already carries one is refused when its IPTC would change."""
    if container not in TIFF_LIKE:
        return
    plan['iptc']['digest'] = False
    carrier = next((x.get('role') for x in (located or {}).get('slots', []) if x['family'] == 'iptc' and x['state'] == 'present'), None)
    if carrier == 'PhotoshopImageResources' and plan['iptc']['changed']:
        raise edits.Refusal('TIFF_PHOTOSHOP_IPTC_CARRIER_UNSUPPORTED', 'the IPTC of this TIFF lives in a Photoshop image-resource block (tag 0x8649); ExifTool 13.55 would write a second IPTC carrier (tag 0x83BB) beside the stale one, so an IPTC change is refused (reading is unaffected)',
                            '$.edits', container=container, limitation='tiffPhotoshopIptcCarrierWriteUnsupported')
    if digest_before and plan['iptc']['changed']:
        raise edits.Refusal('TIFF_IPTC_DIGEST_UNSUPPORTED', 'this TIFF carries an IPTC digest and the plan would change its IPTC; ExifTool 13.55 cannot refresh it for a TIFF (it warns that the digest is not current)',
                            '$.edits', container=container, limitation='tiffIptcDigestNotRefreshable')


def psir_tail_guard(item, plan, at='$.edits'):
    """An opaque remainder after the last Photoshop image resource (shorter than a resource header, so the shared reader ignores it) is dropped by native 13.55 when it rewrites the
    block for an IPTC change (observed, mailbox 7). Rewriting the block is refused precisely before any native process; a plan that leaves IPTC alone never rewrites it."""
    if not plan['iptc']['changed'] and not plan['declared'].get('iptc'):
        return
    located = item['located']
    tail = (located.get('layout') or {}).get('psir', {}).get('tailBytes', 0) if item['walk'] is None else None
    if item['walk'] is not None:
        for segment in item['walk']['pre']:
            if segment['role'] == 'iptc':
                found = e5payloads.psir_tail(segment['body'])
                tail = len(found.rstrip(b'\0')) if found else 0
    if tail:
        raise edits.Refusal('IPTC_RESOURCE_TAIL_UNSUPPORTED', 'the Photoshop resource block ends with %d opaque byte(s) that no resource owns; ExifTool 13.55 drops them when it rewrites the block, so an IPTC change is refused' % tail,
                            at, tailBytes=tail, limitation='photoshopResourceTailOpaque')


def write_guards(item, plan):
    """The container guards of an E3 time or location plan and of an E4 transfer (the same shared guards the E2 edit applies): HEIF never creates a missing metadata item, a TIFF/DNG IPTC
    rewrite keeps its digest rules, and an opaque Photoshop-resource tail is never rewritten, in a JPEG either: every plan that would rebuild the IPTC (time, transfer or sidecar) meets the
    one tail guard, a JPEG plan that leaves its IPTC alone does not. An unchanged plan passes untouched."""
    if plan.get('kind') == 'unchanged':
        return
    at = '$.items[%s]' % item['id'] if plan.get('kind') != 'edit' else '$.edits'
    creation_guard(item['container'], item['payloads'], plan, at)
    empty_item_guard(item['container'], item['payloads'], plan, at)
    psir_tail_guard(item, plan, at)
    tiff_iptc_guard(item['container'], plan, digest_present(item['located']), item['located'])


def row_key(ifd, tag):
    return '%s:%#06x' % (IFD_PATHS[ifd], tag)


def exif_targets(plan_):
    """``{(ifd, tag)}`` the plan writes or deletes in Exif IFDs, and the set of IFDs it deletes wholesale."""
    targets, deleted = set(), set()
    if plan_['kind'] in ('time', 'location', 'unchanged'):
        return {tuple(t) for t in plan_.get('exifTargets', ())}, set()
    if plan_['kind'] == 'edit':
        by_write = {d['write']: d for name in plan_['fields'] for d in edits.writes.fields()[name]['destinations']}
        for f in plan_['fields'].values():
            for d in f['destinations']:
                if d['family'] == 'exif' and d['state'] in ('write', 'delete'):
                    spec = by_write[d['write']]
                    targets.add((spec['ifd'], int(spec['tag'], 16)))
    else:
        deleted = {{'GPS:all': 'GPS', 'IFD1:all': 'IFD1'}[b] for b in plan_['blocks'] if b in ('GPS:all', 'IFD1:all')}
        targets = {(e['ifd'], int(e['tag'], 16)) for e in plan_['selectors'].get('exif', []) if '%s:%s' % (e['ifd'], e['tag']) in plan_['found']['exif']}
    return targets, deleted


def allowed(before_located, plan_):
    """The fingerprint rows (and bare roles) that this plan may change: planned Exif targets of a TIFF/DNG (their entries are fingerprint rows) and deleted whole IFDs."""
    if 'minimise' in plan_:
        return tuple(sorted((r[0], r[1]) for r in before_located['protected'] if r[0] == 'png/text'))      # a minimised PNG loses its text chunks (named, closed list)
    if before_located['container'] not in TIFF_LIKE:
        return ()
    targets, deleted = exif_targets(plan_)
    rows = {('tiff/entry', row_key(ifd, tag)) for ifd, tag in targets if ifd in IFD_PATHS}
    for ifd in deleted:
        prefix = IFD_PATHS[ifd] + ':'
        rows |= {(r[0], r[1]) for r in before_located['protected'] if r[0] == 'tiff/entry' and r[1].startswith(prefix)}
    return tuple(sorted(rows))


def side_effect(container, before_located, after_located):
    """The ``ctx['extra']`` hook for ``proofs.native_diff``: ``extra(key, before, after) -> rule id or None``, closed and value-aware per container."""
    def rule(key, a, b):
        group0, group1, name = key
        if container in TIFF_LIKE and group0 == 'EXIF' and name in ('StripOffsets', 'TileOffsets') and len(a) == len(b) == 1 and len(str(a[0]).split()) == len(str(b[0]).split()):
            return 'E5-tiffExtentRelocated'          # same number of extents, new offsets: the image bytes themselves are proved equal by P
        if container == 'heif' and (group1, name) in (('QuickTime', 'MediaDataSize'), ('QuickTime', 'MediaDataOffset')) and a and b:
            return 'E5-heifMediaDataBox'
        if container == 'heif' and (group1, name) == ('QuickTime', 'MediaData') and len(a) == len(b) == 1 and all(BINARY_SIZE.fullmatch(x) for x in (a[0], b[0])):
            return 'E5-heifMediaDataBox'             # the listed size of the media-data box follows the rebuilt metadata items; every other item payload is proved equal by P
        before_x, after_x = 'flags' in (before_located['frame'] or {}), 'flags' in (after_located['frame'] or {})
        if (group0, group1, name) == ('File', 'File', 'ExifByteOrder') and len(a) == 1 and not b and not after_located['exif']:
            return 'E5-exifBlockRemoved'             # every Exif entry was deleted, so the Exif block (and its byte order) is gone; P and the residual proof judge the rest
        if container == 'webp' and (group0, group1, name) == ('File', 'File', 'FileType') and len(a) == len(b) == 1 and before_x != after_x:
            created, removed = (str(b[0]) == 'Extended ' + str(a[0]) and after_x), (str(a[0]) == 'Extended ' + str(b[0]) and before_x)
            if (created or removed) and str(a[0] if created else b[0]).startswith('WEBP'):
                return 'E5-webpVp8xCreated' if created else 'E5-webpVp8xRemoved'     # the file type name follows the VP8X; P and the AM-16R layout proof judge the layout itself
        if container == 'webp' and (group0, group1, name) == ('RIFF', 'RIFF', 'WebP_Flags'):
            if after_x and b == [str(after_located['frame']['flags'])]:
                return 'E5-webpVp8xFlags'            # equals the flags byte of the output's own VP8X (AM-16R proves E/X/I/L/A)
            if not after_x and a and not b:
                return 'E5-webpVp8xRemoved'
        if container == 'webp' and group0 == 'RIFF' and name in ('ImageWidth', 'ImageHeight') and a and b and set(map(str, b)) == set(map(str, a)):
            return 'E5-webpCanvasReportedTwice'      # a created VP8X reports the size once more; the values are unchanged
        if container in ('png', 'webp', 'heif') and (group1, name) == ('IFD0', 'YCbCrPositioning') and not a and b == [1]:
            return 'E5-exifMandatoryYCbCrPositioning'
        return None
    return rule
