"""Classic TIFF and DNG layout analyser and locator (TIFF 6.0, Exif, DNG 1.7.1; standard library only).

One bounded walk covers the IFD0 chain, SubIFDs, ExifIFD, GPS and InteropIFD with a single visited-offset set, accounts for every byte
range the structure owns (header, IFD tables, out-of-line values, image extents) and fingerprints the result without offsets. A strip or tile
may therefore be relocated by a writer, but its index, length and bytes are protected, as is every entry value of every IFD except the pointer
and metadata-slot tags.

Write admission follows AM-18R. Unrecognised tags (outside the pinned sets in ``tifftags.json``) are protected as raw bytes and never
interpreted. A write is refused when an unrecognised tag exists and the file has non-padding bytes that no walked structure accounts for,
when an unrecognised value holds a 4-byte-aligned word equal to the start of an accounted region, or when an unrecognised tag has the IFD
type. The published limitation ``tiffUnknownTagSemanticsNotInterpreted`` states what that does not cover. Reading is never narrowed by these
rules. Classic TIFF only: BigTIFF and maker raw files (TIFF/EP) are unsupported by name.
"""
import json
from pathlib import Path
import hashlib
import struct

from schemaxis.adaptors.exiftool import e5common as common, e5payloads as payloads, iptc, xmp

MAX_BYTES = 256 * 1024 * 1024
MAX_CHAIN = 64
MAX_SUBIFDS = 32
MAX_DEPTH = 3
MAX_IFDS = 1024
MAX_ENTRIES = 1024
MAX_EXTENTS = 65536
MAX_SCAN = 4 * 1024 * 1024
SIZES = {1: 1, 2: 1, 3: 2, 4: 4, 5: 8, 6: 1, 7: 1, 8: 2, 9: 4, 10: 8, 11: 4, 12: 8, 13: 4, 16: 8, 17: 8, 18: 8}
BIG_TYPES = (16, 17, 18)
POINTER_TAGS = (0x0111, 0x0144, 0x014A, 0x8769, 0x8825, 0xA005, 0x0201)
SLOT_TAGS = (0x02BC, 0x83BB)
UNSUPPORTED_OFFSET_TAGS = (0x0120, 0x0207, 0x0208, 0x0209, 0x8781, 0xA010, 0xBCC0, 0xBCC2)
RAW_PHOTOMETRIC = (32803, 34892)
DNG_VERSION, DNG_PRIVATE = 0xC612, 0xC634
EXTENT_TAGS = ((0x0111, 0x0117, 'strip'), (0x0144, 0x0145, 'tile'), (0x0201, 0x0202, 'jpeg'))
_TAGS = {}


def tags(context):
    if not _TAGS:
        document = json.loads(Path(__file__).with_name('tifftags.json').read_text())
        for name, table in document['contexts'].items():
            _TAGS[name] = frozenset(int(key, 16) for key in table)
    return _TAGS[context]


def header(data):
    """``(order, first_ifd)``; ``Refused`` for BigTIFF, maker raw signatures and anything that is not a classic TIFF."""
    refused = common.Refused
    if len(data) < 8:
        raise refused('UNSUPPORTED_MEDIA', 'the file is too short to be a TIFF')
    magic = bytes(data[:4])
    if magic in (b'II+\0', b'MM\0+'):
        raise refused('TIFF_BIG_UNSUPPORTED', 'BigTIFF is not supported')
    if magic not in (b'II*\0', b'MM\0*'):
        raise refused('UNSUPPORTED_MEDIA', 'the file has no classic TIFF header')
    if bytes(data[8:10]) == b'CR':
        raise refused('RAW_FORMAT_UNSUPPORTED', 'a Canon CR2 raw file is a maker TIFF variant that is not supported')
    order = '<' if magic[:2] == b'II' else '>'
    return order, struct.unpack_from(order + 'I', data, 4)[0]


class Walk:
    def __init__(self, data):
        self.data = data
        self.view = memoryview(data)
        self.order, first = header(data)
        self.first = first
        self.ifds, self.regions, self.problems, self.visited = [], [('header', 0, 8, 'header', None)], [], set()
        self.refusals = []

    def problem(self, code, message, path, **observed):
        self.problems.append((code, message, path, observed))

    def read_ifd(self, offset, path, context, depth):
        n, o = len(self.data), self.order
        if offset < 8 or offset + 2 > n:
            self.problem('INVALID_EXIF_STRUCTURE', 'an IFD offset lies outside the TIFF data or inside its header', path, offset=offset)
            return None
        if offset in self.visited:
            self.problem('INVALID_EXIF_STRUCTURE', path + ' repeats an earlier IFD (cycle or shared offset)', path, offset=offset)
            return None
        if len(self.ifds) >= MAX_IFDS:
            self.problem('TIFF_IFD_BUDGET', 'the file has more than %d IFDs' % MAX_IFDS, path)
            return None
        self.visited.add(offset)
        count = struct.unpack_from(o + 'H', self.data, offset)[0]
        end = offset + 2 + 12 * count + 4
        if count > MAX_ENTRIES:
            self.problem('TIFF_IFD_BUDGET', path + ' has more than %d entries' % MAX_ENTRIES, path, entries=count)
            return None
        if end > n:
            self.problem('INVALID_EXIF_STRUCTURE', path + ' entry table is truncated', path, entries=count)
            return None
        self.regions.append(('table', offset, end, path, None))
        entries, damaged = [], False
        for index in range(count):
            base = offset + 2 + 12 * index
            tag, kind, number = struct.unpack_from(o + 'HHI', self.data, base)
            size = SIZES.get(kind)
            row = {'tag': tag, 'type': kind, 'count': number, 'field': base + 8, 'offset': None, 'raw': None, 'known': size is not None, 'path': path, 'context': context}
            if size is None:
                entries.append(row)
                continue
            length = size * number
            if length <= 4:
                row['raw'] = self.view[base + 8:base + 8 + length]
            else:
                where = struct.unpack_from(o + 'I', self.data, base + 8)[0]
                if where < 8 or where + length > n:
                    self.problem('INVALID_EXIF_STRUCTURE', 'an IFD value lies outside the TIFF data', path, tag=tag, offset=where, bytes=length)
                    damaged = True
                    continue
                row['offset'], row['raw'] = where, self.view[where:where + length]
                self.regions.append(('value', where, where + length, path, tag))
            entries.append(row)
        following = struct.unpack_from(o + 'I', self.data, end - 4)[0]
        if damaged:
            return None
        ifd = {'path': path, 'context': context, 'offset': offset, 'entries': entries, 'next': following, 'depth': depth}
        self.ifds.append(ifd)
        return ifd

    def values(self, row, kinds=(3, 4)):
        if row['type'] not in kinds or row['raw'] is None:
            return None
        fmt = {3: 'H', 4: 'I'}[row['type']]
        return list(struct.unpack(self.order + fmt * row['count'], bytes(row['raw'])))

    def chain(self, offset, path, context, depth):
        index = 0
        while offset:
            if index >= MAX_CHAIN:
                self.problem('TIFF_IFD_BUDGET', 'the IFD chain is longer than %d' % MAX_CHAIN, path)
                return
            name = path if index == 0 else ('IFD%d' % index if path == 'IFD0' else '%s+%d' % (path, index))
            ifd = self.read_ifd(offset, name, context, depth)
            if ifd is None:
                return
            self.follow(ifd)
            offset = ifd['next']
            index += 1

    def follow(self, ifd):
        path, context, depth = ifd['path'], ifd['context'], ifd['depth']
        wanted = {'image': ((0x8769, 'Exif', 'exif'), (0x8825, 'GPS', 'gps')), 'exif': ((0xA005, 'Interop', 'interop'),)}.get(context, ())
        for tag, label, child in wanted:
            rows = [r for r in ifd['entries'] if r['tag'] == tag]
            if not rows:
                continue
            row = rows[0]
            if len(rows) > 1 or row['type'] not in (4, 13) or row['count'] != 1 or row['raw'] is None:
                self.problem('INVALID_EXIF_STRUCTURE', '%s pointer is repeated or is not one LONG' % label, path)
                continue
            self.read_ifd_child(struct.unpack(self.order + 'I', bytes(row['raw']))[0], '%s/%s' % (path, label), child, depth)
        if context != 'image':
            return
        rows = [r for r in ifd['entries'] if r['tag'] == 0x014A]
        if not rows:
            return
        row = rows[0]
        if len(rows) > 1 or row['type'] not in (4, 13) or row['raw'] is None:
            self.problem('INVALID_EXIF_STRUCTURE', 'the SubIFDs pointer is repeated or is not LONG or IFD', path)
        elif row['count'] > MAX_SUBIFDS or depth + 1 > MAX_DEPTH:
            self.problem('TIFF_IFD_BUDGET', 'SubIFDs exceed %d children or %d levels' % (MAX_SUBIFDS, MAX_DEPTH), path)
        else:
            for index, offset in enumerate(struct.unpack(self.order + 'I' * row['count'], bytes(row['raw']))):
                self.chain(offset, '%s/SubIFD[%d]' % (path, index), 'image', depth + 1)

    def read_ifd_child(self, offset, path, context, depth):
        ifd = self.read_ifd(offset, path, context, depth + 1)
        if ifd is not None:
            if ifd['next']:
                self.problem('INFO_IGNORED_NEXT', path + ' has a next-IFD offset that is not followed', path)
            self.follow(ifd)

    def extents(self):
        """Image extents of every image IFD: ``[(path, label, index, offset, length)]``; faults become problems."""
        out, n = [], len(self.data)
        for ifd in self.ifds:
            if ifd['context'] != 'image':
                continue
            for offset_tag, count_tag, label in EXTENT_TAGS:
                starts = [r for r in ifd['entries'] if r['tag'] == offset_tag]
                counts = [r for r in ifd['entries'] if r['tag'] == count_tag]
                if not starts and not counts:
                    continue
                single = len(starts) == 1 and len(counts) == 1 and all(r['type'] in (3, 4) and r['raw'] is not None for r in (starts[0], counts[0]))
                if not single or starts[0]['count'] != counts[0]['count'] or not starts[0]['count']:
                    self.problem('TIFF_IMAGE_EXTENT_INVALID', 'the %s offsets and byte counts of %s are missing, repeated, mistyped or unequal in number' % (label, ifd['path']), ifd['path'])
                    continue
                if starts[0]['count'] > MAX_EXTENTS:       # the declared count is judged BEFORE any array is unpacked: a hostile count never allocates
                    self.problem('TIFF_IFD_BUDGET', '%s has more than %d %s extents' % (ifd['path'], MAX_EXTENTS, label), ifd['path'])
                    continue
                values_a, values_b = self.values(starts[0]), self.values(counts[0])
                for index, (start, length) in enumerate(zip(values_a, values_b)):
                    if start + length > n:
                        self.problem('TIFF_IMAGE_EXTENT_INVALID', 'a %s extent of %s lies beyond the end of the file' % (label, ifd['path']), ifd['path'], index=index)
                        continue
                    out.append((ifd['path'], label, index, start, length))
                    if length:
                        self.regions.append(('extent', start, start + length, ifd['path'], '%s[%d]' % (label, index)))
        return out


def accounting(regions, data):
    """Overlaps (``[(a, b)]``), non-padding gaps (``[(start, end)]``) and region start offsets of a region list."""
    ordered = sorted((r for r in regions if r[2] > r[1]), key=lambda r: (r[1], r[2]))
    overlaps, gaps, position, widest = [], [], 0, None
    for region in ordered:
        if widest is not None and region[1] < widest[2] and not (region[0] == 'value' and widest[0] == 'value'):
            overlaps.append((widest, region))
        if region[1] > position:
            gaps.append((position, region[1]))
        if region[2] > position:
            position = region[2]
        if widest is None or region[2] > widest[2]:
            widest = region
    if position < len(data):
        gaps.append((position, len(data)))
    real = [(a, b) for a, b in gaps if not (b - a < 4 and bytes(data[a:b]) == bytes(b - a))]
    starts = {r[1] for r in ordered if r[0] != 'header'}
    return overlaps, real, starts


def locate(data):
    if len(data) > MAX_BYTES:
        raise common.Refused('PHOTO_RESOURCE_LIMIT', 'the file exceeds %d bytes' % MAX_BYTES, bytes=len(data))
    walk = Walk(data)
    walk.chain(walk.first, 'IFD0', 'image', 0)
    if not walk.ifds or walk.ifds[0]['path'] != 'IFD0':
        code, message, *_ = walk.problems[0] if walk.problems else ('INVALID_EXIF_STRUCTURE', 'IFD0 cannot be read', None, {})
        raise common.Refused(code if code != 'INFO_IGNORED_NEXT' else 'INVALID_EXIF_STRUCTURE', message)
    extents = walk.extents()
    overlaps, gaps, starts = accounting(walk.regions, data)
    ifd0 = walk.ifds[0]
    versions = [r for r in ifd0['entries'] if r['tag'] == DNG_VERSION]
    is_dng = bool(versions)
    for ifd in walk.ifds:
        if ifd['context'] == 'image' and not is_dng:
            for row in ifd['entries']:
                if row['tag'] == 0x0106 and (walk.values(row) or [None])[0] in RAW_PHOTOMETRIC:
                    raise common.Refused('RAW_FORMAT_UNSUPPORTED', 'a colour-filter-array or linear-raw image without a DNG version is a maker raw variant that is not supported',
                                         ifd=ifd['path'])
    result = common.new_result('dng' if is_dng else 'tiff')
    notes = result['notes']
    for code, message, path, observed in walk.problems:
        if code == 'INFO_IGNORED_NEXT':
            notes.append('tiffNextIfdNotFollowed:' + path)
            continue
        notes.append('%s:%s' % (code, path))
        common.refuse_write(result, code, message, ifd=path, **observed)
    for first, second in overlaps:
        notes.append('TIFF_LAYOUT_OVERLAP')
        common.refuse_write(result, 'TIFF_LAYOUT_OVERLAP', 'the %s of %s overlaps the %s of %s' % (first[0], first[3], second[0], second[3]), first=list(first[:4]), second=list(second[:4]))
    values = sorted((r for r in walk.regions if r[0] == 'value' and r[2] > r[1]), key=lambda r: r[1])
    if any(b[1] < a[2] for a, b in zip(values, values[1:])):
        notes.append('tiffSharedValueBlocks')
    # Unrecognised tags, unsupported types and offset tags (AM-18R).
    unrecognised = []
    for ifd in walk.ifds:
        known = tags(ifd['context'])
        for row in ifd['entries']:
            if not row['known']:
                common.refuse_write(result, 'TIFF_TYPE_UNSUPPORTED', 'entry %#06x of %s has an unsupported type %d' % (row['tag'], ifd['path'], row['type']), ifd=ifd['path'], tag=row['tag'])
            if row['type'] in BIG_TYPES:
                common.refuse_write(result, 'TIFF_BIG_UNSUPPORTED', 'entry %#06x of %s uses a BigTIFF type' % (row['tag'], ifd['path']), ifd=ifd['path'], tag=row['tag'])
            if row['tag'] in UNSUPPORTED_OFFSET_TAGS:
                common.refuse_write(result, 'TIFF_OFFSET_TAG_UNSUPPORTED', 'the offset tag %#06x of %s is rewritten by the native writer but not modelled here' % (row['tag'], ifd['path']), ifd=ifd['path'], tag=row['tag'])
            if row['tag'] not in known:
                unrecognised.append(row)
    if unrecognised:
        result['limitations'].append('tiffUnknownTagSemanticsNotInterpreted')
        notes.append('tiffUnknownTags:' + ','.join('%s:%#06x' % (r['path'], r['tag']) for r in unrecognised))
    suspect = []
    for row in unrecognised:
        if row['type'] == 13:
            common.refuse_write(result, 'TIFF_UNKNOWN_IFD_POINTER', 'the unrecognised tag %#06x of %s has the IFD type' % (row['tag'], row['path']), ifd=row['path'], tag=row['tag'])
            suspect.append(row)
        if row['type'] in (1, 4, 6, 7, 9, 13) and row['raw'] is not None:
            raw = row['raw']
            if len(raw) > MAX_SCAN:
                reason = 'tooLargeToScan'
            else:
                words = [w[0] for w in struct.iter_unpack(walk.order + 'I', bytes(raw[:len(raw) // 4 * 4]))]
                reason = 'regionStart' if any(w in starts for w in words) else None
            if reason:
                common.refuse_write(result, 'TIFF_UNKNOWN_OFFSET_SUSPECT', 'the unrecognised tag %#06x of %s holds a word equal to the start of a structure' % (row['tag'], row['path']),
                                    reason=reason, ifd=row['path'], tag=row['tag'])
                suspect.append(row)
    if unrecognised and gaps:
        common.refuse_write(result, 'TIFF_UNKNOWN_OFFSET_SUSPECT', 'unrecognised tags exist and %d byte ranges of the file belong to no walked structure' % len(gaps), reason='unaccountedBytes',
                            gaps=[list(g) for g in gaps[:8]], tags=['%s:%#06x' % (r['path'], r['tag']) for r in unrecognised][:16])
        suspect.extend(unrecognised)
    if suspect:
        notes.append('tiffUnknownOffsetSuspect:' + ','.join(sorted({'%s:%#06x' % (r['path'], r['tag']) for r in suspect})))
    elif gaps:
        notes.append('tiffUnreferencedBytesNotProtected')
    # Frame and pages.
    images = []
    for ifd in walk.ifds:
        if ifd['context'] != 'image':
            continue
        facts = {'path': ifd['path']}
        for tag, name in ((0x0100, 'width'), (0x0101, 'height'), (0x00FE, 'newSubfileType'), (0x0103, 'compression'), (0x0106, 'photometric')):
            row = next((r for r in ifd['entries'] if r['tag'] == tag), None)
            value = walk.values(row) if row else None
            facts[name] = value[0] if value else None
        images.append(facts)
    main = [i for i in walk.ifds if i['context'] == 'image' and '/' not in i['path'] and '+' not in i['path']]
    result['frame'] = {'width': images[0]['width'], 'height': images[0]['height'], 'pages': len(main), 'images': images}
    if len(main) > 1:
        notes.append('tiffMultiPage')
    for ifd in main[1:]:
        if any(r['tag'] in (0x0201, 0x0202) for r in ifd['entries']):
            notes.append('tiffJpegThumbnailIfd:' + ifd['path'])
    # Payloads.
    result['exif'].append(data)
    result['slots'].append(common.slot('exif', 'present', role='IFD0', count=1))
    xmp_rows = [r for r in ifd0['entries'] if r['tag'] == 0x02BC]
    if not xmp_rows:
        result['slots'].append(common.slot('xmp', 'absent', role='0x02BC'))
    elif len(xmp_rows) > 1:
        result['xmp'].extend(bytes(r['raw']) for r in xmp_rows if r['raw'] is not None and r['type'] in (1, 2, 7) and len(r['raw']) <= xmp.MAX_BYTES)
        result['slots'].append(common.slot('xmp', 'ambiguous', role='0x02BC', count=len(xmp_rows)))
        common.refuse_write(result, 'TIFF_DUPLICATE_METADATA_TAG', 'IFD0 has %d XMP tags' % len(xmp_rows), tag=0x02BC)
    else:
        row = xmp_rows[0]
        if row['type'] not in (1, 2, 7) or row['raw'] is None:
            result['slots'].append(common.slot('xmp', 'unreadable', role='0x02BC', count=1, code='INVALID_EXIF_STRUCTURE', message='the XMP tag has an unsuitable type'))
        elif len(row['raw']) > xmp.MAX_BYTES:
            result['slots'].append(common.slot('xmp', 'unreadable', role='0x02BC', count=1, code='XMP_BOUND', message='the XMP value exceeds %d bytes' % xmp.MAX_BYTES))
        else:
            result['xmp'].append(bytes(row['raw']))
            result['slots'].append(common.slot('xmp', 'present', role='0x02BC', count=1))
    carriers = []
    for row in (r for r in ifd0['entries'] if r['tag'] == 0x83BB):
        if row['raw'] is None or row['type'] not in (1, 4, 7):
            carriers.append(('IPTC-NAA', None, 'INVALID_EXIF_STRUCTURE'))
        elif len(row['raw']) > iptc.MAX_BYTES:
            carriers.append(('IPTC-NAA', None, 'IPTC_BOUND'))
        else:
            carriers.append(('IPTC-NAA', payloads.photoshop_body_from_iim(row['raw']), None))
            result['iptcStoredMd5'] = hashlib.md5(bytes(row['raw'])).hexdigest()      # native's CurrentIPTCDigest is the digest of the stored (LONG-padded) bytes
            notes.append('iptcWrappedFromTiffTag83BB')
    for row in (r for r in ifd0['entries'] if r['tag'] == 0x8649):
        if row['raw'] is None or row['type'] not in (1, 7):
            continue
        body = payloads.photoshop_body_from_resources(row['raw'])
        found = payloads.has_iptc_resource(body)
        if found:
            carriers.append(('PhotoshopImageResources', body, None))
        elif found is None:
            notes.append('photoshopResourcesMalformed')
    result['iptc'].extend(c[1] for c in carriers if c[1] is not None)
    if not carriers:
        result['slots'].append(common.slot('iptc', 'absent', role='0x83BB'))
    elif len(carriers) > 1:
        result['slots'].append(common.slot('iptc', 'ambiguous', role=carriers[0][0], count=len(carriers)))
    elif carriers[0][2]:
        result['slots'].append(common.slot('iptc', 'unreadable', role=carriers[0][0], count=1, code=carriers[0][2], message='the IPTC carrier cannot be read: ' + carriers[0][2]))
    else:
        result['slots'].append(common.slot('iptc', 'present', role=carriers[0][0], count=1))
    # DNG facts.
    if is_dng:
        if versions[0]['raw'] is None or bytes(versions[0]['raw'][:1]) != b'\x01':
            notes.append('dngVersionUnexpected')
        private = next((r for r in ifd0['entries'] if r['tag'] == DNG_PRIVATE), None)
        if private is not None and private['raw'] is not None and bytes(private['raw'][:10]) == b'Adobe\0MakN':
            notes.append('dngPrivateDataAdobeMakN')
            block = bytes(private['raw'][10:14])
            if len(block) < 4 or struct.unpack('>I', block)[0] > len(private['raw']) - 14:
                notes.append('dngPrivateAdobeMakNMalformed')
        result['limitations'].append('makerNoteMayIdentifyDevice')
    if any(r['tag'] == 0x927C for ifd in walk.ifds for r in ifd['entries']):
        notes.append('makerNoteOpaqueByteEqualOnly')
    # Fingerprint, offset-free.
    order_bytes = b'II' if walk.order == '<' else b'MM'
    result['protected'].append(common.entry('tiff/header', 'byteOrder', order_bytes))
    psir = psir_facts = None
    for ifd in walk.ifds:
        seen = {}
        for row in ifd['entries']:
            if row['tag'] in POINTER_TAGS or row['tag'] in SLOT_TAGS:
                continue
            if row['tag'] == 0x8649 and ifd['path'] == 'IFD0' and row['raw'] is not None and row['type'] in (1, 7):
                walked = payloads.psir_walk(row['raw'])
                if walked is not None:      # the Photoshop block is a metadata carrier: its IPTC-NAA (0x0404) and digest (0x0425) resources are slots, every other resource and the tail are protected rows
                    psir = walked
                    counts = {}
                    for ident, name, data in walked[0]:
                        if ident in (0x0404, 0x0425):
                            continue
                        counts[ident] = counts.get(ident, 0) + 1
                        result['protected'].append(common.entry('tiff/psir', 'IFD0:0x8649:res[%#06x#%d]' % (ident, counts[ident] - 1), bytes([len(name)]) + name + data))
                    tail = walked[1].rstrip(b'\0') if len(walked[1]) <= 1 else walked[1]
                    if tail:
                        result['protected'].append(common.entry('tiff/psir', 'IFD0:0x8649:tail', tail))
                        result['limitations'].append('photoshopResourceTailOpaque')
                        common.refuse_write(result, 'IPTC_RESOURCE_TAIL_UNSUPPORTED', 'the Photoshop resource block ends with %d opaque byte(s) that no resource owns; ExifTool 13.55 drops them whenever it rewrites the block' % len(tail), tailBytes=len(tail))
                    psir_facts = {'resources': [ident for ident, _, _ in walked[0]], 'tailBytes': len(tail)}
                    continue
            index = seen.get(row['tag'], 0)
            seen[row['tag']] = index + 1
            key = '%s:%#06x%s' % (ifd['path'], row['tag'], '' if index == 0 else '#%d' % index)
            raw = bytes(row['raw']) if row['raw'] is not None else b'<unknown-type>'
            result['protected'].append(common.entry('tiff/entry', key, struct.pack(walk.order + 'HHI', row['tag'], row['type'], row['count']) + raw))
            if row['offset'] is not None:
                result['ranges'].append(('tiff/entry', key, row['offset'], len(row['raw'])))
    for path, label, index, start, length in extents:
        key = '%s:%s[%d]' % (path, label, index)
        result['protected'].append(common.entry('tiff/extent', key, walk.view[start:start + length]))
        result['ranges'].append(('tiff/extent', key, start, length))
    if psir is not None:
        notes.append('photoshopResourceBlock')
    result['layout'] = {'ifds': [{'path': i['path'], 'context': i['context'], 'offset': i['offset'], 'entries': len(i['entries'])} for i in walk.ifds],
                        'unaccounted': [list(g) for g in gaps], 'unrecognised': [{'path': r['path'], 'tag': r['tag'], 'type': r['type'], 'count': r['count']} for r in unrecognised],
                        'byteOrder': 'II' if walk.order == '<' else 'MM', **({'psir': psir_facts} if psir_facts else {})}
    return common.finish(result)
