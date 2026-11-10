"""HEIF/HEIC/AVIF bounded ISO-BMFF locator (public MPEG drafts of ISO/IEC 14496-12 and 23008-12; standard library only).

Basis label ``P-draft``: the 14496-12 8th-edition second DIS text (w23813) and the 23008-12 FDIS with COR1 (w18310). Every result carries the
limitation ``heifSpecDraftOnly``. The locator reads boxes with hard bounds (top-level boxes, nested boxes, depth, items, extents) and models
exactly what a metadata edit must not disturb:

* Extent resolution (14496-12 8.11.3): construction method 0 counts from the file start, 1 from the start of ``idat``, 2 is permitted by the
  standard but unsupported here. ``base_offset`` is additive. An ``extent_length`` of 0, explicit or implied by ``length_size`` 0, means
  "to the end of the file or of ``idat``", never "empty"; such an extent is resolved that way and flagged, because a metadata slot reading
  zero bytes there would hide the real content. A slot item with an implied extent is ``unreadable`` (``HEIF_IMPLIED_EXTENT``) and every write
  is refused.
* Primary association: the Exif slot of the primary image is the set of ``Exif`` items with a ``cdsc`` reference to ``pitm``; XMP likewise for
  ``mime`` items of type ``application/rdf+xml``. More than one item is ``ambiguous``; an item that also describes another image is shared.
  Metadata items not linked to the primary image are protected like image items.
* The fingerprint holds whole ``infe`` boxes, reassembled payloads of every non-slot item, ``iprp``, every ``iref`` entry except ``cdsc``
  entries from slot items (normalised, independent of box version), the other ``meta`` children and the other top-level boxes, without offsets.

Nothing is decoded; payloads are opaque bytes.
"""
import struct

from schemaxis.adaptors.exiftool import e5common as common, e5payloads as payloads, xmp

MAX_BYTES = 64 * 1024 * 1024
MAX_TOP = 64
MAX_NESTED = 4096
MAX_DEPTH = 8
MAX_ITEMS = 4096
MAX_EXTENTS = 1024
BRANDS = (b'heic', b'heix', b'mif1', b'avif')
PLAIN = (b'iprp', b'ipco', b'dinf', b'grpl', b'moov', b'trak', b'mdia', b'minf', b'stbl', b'edts', b'udta')
DERIVED = (b'grid', b'iovl', b'iden')
XMP_TYPE = 'application/rdf+xml'
OTHER_TOP_SKIP = (b'ftyp', b'meta', b'mdat', b'free', b'skip')
META_NAMED = (b'hdlr', b'pitm', b'iinf', b'iloc', b'iprp', b'iref', b'idat')


def invalid(message, **observed):
    return common.Refused('INVALID_PHOTO_DATA', message, **observed)


def bound(message, **observed):
    return common.Refused('HEIF_BOUND', message, **observed)


class Boxes:
    def __init__(self, data):
        self.data, self.nested = data, 0

    def read(self, start, end, depth, top=False):
        out, position, data = [], start, self.data
        while position < end:
            if end - position < 8:
                raise invalid('a box header is truncated', offset=position)
            size, kind = struct.unpack_from('>I4s', data, position)
            header = 8
            if size == 1:
                if end - position < 16:
                    raise invalid('a box largesize is truncated', offset=position)
                size, header = struct.unpack_from('>Q', data, position + 8)[0], 16
            elif size == 0:
                if not top:
                    raise invalid('a nested box declares the size 0', offset=position)
                size = end - position
            if kind == b'uuid':
                header += 16
            if size < header or position + size > end:
                raise invalid('a box size is invalid or exceeds its parent', box=kind.decode('latin-1'), offset=position)
            if depth > MAX_DEPTH:
                raise bound('boxes nest deeper than %d levels' % MAX_DEPTH)
            if top:
                if len(out) >= MAX_TOP:
                    raise bound('more than %d top-level boxes' % MAX_TOP)
            else:
                self.nested += 1
                if self.nested > MAX_NESTED:
                    raise bound('more than %d nested boxes' % MAX_NESTED)
            node = {'type': kind, 'start': position, 'header': header, 'end': position + size, 'children': []}
            body = position + header
            if kind in PLAIN:
                node['children'] = self.read(body, node['end'], depth + 1)
            elif kind == b'meta':
                if size < header + 4:
                    raise invalid('the meta box is truncated', offset=position)
                node['children'] = self.read(body + 4, node['end'], depth + 1)
            out.append(node)
            position += size
        return out


def uint(data, position, size, end):
    if size == 0:
        return 0
    if position + size > end:
        raise invalid('a box field is truncated', offset=position)
    return int.from_bytes(data[position:position + size], 'big')


def cstring(data, position, end):
    stop = data.find(b'\0', position, end)
    if stop < 0:
        return None, end
    return bytes(data[position:stop]), stop + 1


def parse_infe(data, node):
    position, end = node['start'] + node['header'], node['end']
    if end - position < 4:
        return None
    version, flags = data[position], int.from_bytes(data[position + 1:position + 4], 'big')
    position += 4
    wide = version >= 3
    if end - position < (4 if wide else 2) + 2:
        return None
    ident = uint(data, position, 4 if wide else 2, end)
    position += 4 if wide else 2
    protection = uint(data, position, 2, end)
    position += 2
    item = {'id': ident, 'protection': protection, 'hidden': bool(flags & 1), 'type': None, 'name': None, 'contentType': None, 'version': version,
            'start': node['start'], 'end': end, 'problems': []}
    if version >= 2:
        if end - position < 4:
            return None
        item['type'] = bytes(data[position:position + 4])
        position += 4
    name, position = cstring(data, position, end)
    item['name'] = name
    if name is None:
        item['problems'].append('infe name is not terminated')
    elif item['type'] == b'mime' or version < 2:
        content, position = cstring(data, position, end)
        item['contentType'] = content.decode('latin-1') if content is not None else None
        if content is None and item['type'] == b'mime':
            item['problems'].append('infe content type is not terminated')
    return item


def parse_iloc(data, node):
    position, end = node['start'] + node['header'], node['end']
    if end - position < 8:
        raise invalid('the iloc box is truncated')
    version = data[position]
    if version > 2:
        raise invalid('the iloc version %d is not supported' % version)
    sizes = (data[position + 4] >> 4, data[position + 4] & 15, data[position + 5] >> 4, (data[position + 5] & 15) if version else 0)
    offset_size, length_size, base_size, index_size = sizes
    if any(s not in (0, 4, 8) for s in sizes):
        raise invalid('an iloc field size is not 0, 4 or 8')
    position += 6
    count = uint(data, position, 2 if version < 2 else 4, end)
    position += 2 if version < 2 else 4
    if count > MAX_ITEMS:
        raise bound('iloc lists more than %d items' % MAX_ITEMS)
    items = []
    for _ in range(count):
        ident = uint(data, position, 2 if version < 2 else 4, end)
        position += 2 if version < 2 else 4
        method = 0
        if version:
            method = uint(data, position, 2, end) & 15
            position += 2
        dri = uint(data, position, 2, end)
        base = uint(data, position + 2, base_size, end)
        position += 2 + base_size
        extents_count = uint(data, position, 2, end)
        position += 2
        if extents_count > MAX_EXTENTS:
            raise bound('an iloc item has more than %d extents' % MAX_EXTENTS)
        extents = []
        for _ in range(extents_count):
            position += index_size if version else 0
            extent_offset = uint(data, position, offset_size, end)
            length = uint(data, position + offset_size, length_size, end)
            position += offset_size + length_size
            extents.append((extent_offset, length, length_size == 0 or length == 0))
        problems = []
        if (offset_size == 0 or length_size == 0) and extents_count != 1:
            problems.append('a zero field size is permitted only with one extent')
        items.append({'id': ident, 'method': method, 'dri': dri, 'base': base, 'extents': extents, 'problems': problems})
    return items


def parse_ipma(data, node):
    position, end = node['start'] + node['header'], node['end']
    if end - position < 8:
        raise invalid('the ipma box is truncated')
    version, flags = data[position], int.from_bytes(data[position + 1:position + 4], 'big')
    count = uint(data, position + 4, 4, end)
    position += 8
    if count > MAX_ITEMS:
        raise bound('ipma lists more than %d items' % MAX_ITEMS)
    out = {}
    for _ in range(count):
        ident = uint(data, position, 2 if version < 1 else 4, end)
        position += 2 if version < 1 else 4
        number = uint(data, position, 1, end)
        position += 1
        entries = []
        for _ in range(number):
            if flags & 1:
                value = uint(data, position, 2, end)
                position += 2
                entries.append(value & 0x7FFF)
            else:
                value = uint(data, position, 1, end)
                position += 1
                entries.append(value & 0x7F)
        out.setdefault(ident, []).extend(entries)
    return out


def parse_iref(data, node, boxes):
    position, end = node['start'] + node['header'], node['end']
    if end - position < 4:
        raise invalid('the iref box is truncated')
    version = data[position]
    wide = version >= 1
    out = []
    for child in boxes.read(position + 4, end, 3):
        at, stop = child['start'] + child['header'], child['end']
        width = 4 if wide else 2
        origin = uint(data, at, width, stop)
        count = uint(data, at + width, 2, stop)
        targets = [uint(data, at + width + 2 + width * i, width, stop) for i in range(count)]
        out.append({'type': child['type'], 'from': origin, 'to': targets})
    return out


def locate(data):
    if len(data) > MAX_BYTES:
        raise common.Refused('PHOTO_RESOURCE_LIMIT', 'the file exceeds %d bytes' % MAX_BYTES, bytes=len(data))
    reader = Boxes(data)
    top = reader.read(0, len(data), 1, top=True) if len(data) >= 8 else []
    ftyp = next((b for b in top if b['type'] == b'ftyp'), None)
    if ftyp is None or ftyp['end'] - ftyp['start'] - ftyp['header'] < 8:
        raise common.Refused('UNSUPPORTED_MEDIA', 'the file has no ftyp box of a still-image HEIF family')
    body = ftyp['start'] + ftyp['header']
    major = bytes(data[body:body + 4])
    compatible = [bytes(data[p:p + 4]) for p in range(body + 8, ftyp['end'] - 3, 4)]
    if major not in BRANDS and not any(b in BRANDS for b in compatible):
        raise common.Refused('UNSUPPORTED_MEDIA', 'the ftyp brands are not heic, heix, mif1 or avif', major=major.decode('latin-1'))
    metas = [b for b in top if b['type'] == b'meta']
    if len(metas) != 1:
        raise invalid('a HEIF file needs exactly one top-level meta box', metas=len(metas))
    meta = metas[0]
    children = {}
    for child in meta['children']:
        children.setdefault(child['type'], []).append(child)
    hdlr = children.get(b'hdlr', [None])[0]
    if hdlr is None or bytes(data[hdlr['start'] + hdlr['header'] + 8:hdlr['start'] + hdlr['header'] + 12]) != b'pict':
        raise common.Refused('UNSUPPORTED_MEDIA', 'the meta handler is not pict')
    pitm_box = children.get(b'pitm', [None])[0]
    if pitm_box is None:
        raise invalid('the file has no pitm box')
    pitm_at = pitm_box['start'] + pitm_box['header']
    primary = uint(data, pitm_at + 4, 2 if data[pitm_at] == 0 else 4, pitm_box['end'])
    result = common.new_result('heif')
    notes = result['notes']
    result['brand'] = major.decode('latin-1')
    result['limitations'].append('heifSpecDraftOnly')
    # Items.
    items, order = {}, []
    iinf = children.get(b'iinf', [None])[0]
    if iinf is None:
        raise invalid('the file has no iinf box')
    at = iinf['start'] + iinf['header']
    infe_nodes = reader.read(at + 4 + (2 if data[at] == 0 else 4), iinf['end'], 3)
    if len(infe_nodes) > MAX_ITEMS:
        raise bound('more than %d items' % MAX_ITEMS)
    for node in infe_nodes:
        item = parse_infe(data, node) if node['type'] == b'infe' else None
        if item is None:
            common.refuse_write(result, 'HEIF_REFERENCE_INVALID', 'an item information entry is malformed or is not an infe box')
            notes.append('HEIF_REFERENCE_INVALID')
            continue
        if item['id'] in items:
            common.refuse_write(result, 'HEIF_REFERENCE_INVALID', 'two infe boxes use the item ID %d' % item['id'], item=item['id'])
            notes.append('HEIF_REFERENCE_INVALID')
            continue
        if item['problems']:
            common.refuse_write(result, 'HEIF_REFERENCE_INVALID', 'item %d: %s' % (item['id'], item['problems'][0]), item=item['id'])
        items[item['id']] = item
        order.append(item['id'])
    if primary not in items:
        raise invalid('pitm names an item that iinf does not list', item=primary)
    # Locations and resolved extents.
    iloc = children.get(b'iloc', [None])[0]
    if iloc is None:
        raise invalid('the file has no iloc box')
    idat = children.get(b'idat', [None])[0]
    idat_range = (idat['start'] + idat['header'], idat['end']) if idat else None
    placed = {}
    for entry in parse_iloc(data, iloc):
        if entry['id'] not in items or entry['id'] in placed:
            common.refuse_write(result, 'HEIF_REFERENCE_INVALID', 'iloc names item %d twice or without an infe box' % entry['id'], item=entry['id'])
            notes.append('HEIF_REFERENCE_INVALID')
            continue
        placed[entry['id']] = entry
        item = items[entry['id']]
        item['resolved'], item['implied'] = [], False
        if entry['problems']:
            common.refuse_write(result, 'HEIF_REFERENCE_INVALID', 'item %d: %s' % (entry['id'], entry['problems'][0]), item=entry['id'])
        if entry['method'] not in (0, 1):
            item['unsupported'] = 'HEIF_ITEM_CONSTRUCTION_UNSUPPORTED'
            continue
        if entry['dri']:
            item['unsupported'] = 'HEIF_EXTERNAL_DATA'
            continue
        if entry['method'] == 1 and idat_range is None:
            raise invalid('item %d is constructed from idat but the file has no idat box' % entry['id'])
        origin, limit = (0, len(data)) if entry['method'] == 0 else idat_range
        for extent_offset, length, implied in entry['extents']:
            position = origin + entry['base'] + extent_offset
            if implied:
                length = limit - position
                item['implied'] = True
                if 'heifImpliedExtentLength' not in notes:
                    notes.append('heifImpliedExtentLength')
            if position > limit or length < 0 or position + length > limit:
                raise invalid('an extent of item %d lies outside the %s' % (entry['id'], 'file' if entry['method'] == 0 else 'idat payload'), item=entry['id'])
            item['resolved'].append((position, length))
    for ident, item in items.items():
        if item['protection']:
            common.refuse_write(result, 'HEIF_PROTECTED_ITEM', 'item %d is protected (item_protection_index %d)' % (ident, item['protection']), item=ident)
        if item.get('unsupported'):
            common.refuse_write(result, item['unsupported'], 'item %d cannot be resolved: %s' % (ident, item['unsupported']), item=ident)
        if item.get('implied'):
            common.refuse_write(result, 'HEIF_IMPLIED_EXTENT', 'item %d has an extent length of 0, which means to the end of its container' % ident, item=ident)
    spans = sorted((p, p + n, ident) for ident, item in items.items() for p, n in item.get('resolved', ()) if n > 0)
    furthest = None
    for span in spans:
        if furthest is not None and span[0] < furthest[1] and span[2] != furthest[2]:
            if 'HEIF_EXTENT_OVERLAP' not in notes:
                notes.append('HEIF_EXTENT_OVERLAP')
            common.refuse_write(result, 'HEIF_EXTENT_OVERLAP', 'the extents of items %d and %d overlap' % (furthest[2], span[2]), items=[furthest[2], span[2]])
        if furthest is None or span[1] > furthest[1]:
            furthest = span
    # References.
    refs = parse_iref(data, children[b'iref'][0], reader) if b'iref' in children else []
    for ref in refs:
        if ref['from'] not in items or any(t not in items for t in ref['to']) or len(set(ref['to'])) != len(ref['to']):
            notes.append('HEIF_REFERENCE_INVALID')
            common.refuse_write(result, 'HEIF_REFERENCE_INVALID', 'an iref %s entry names a missing item or repeats a target' % ref['type'].decode('latin-1'), reference=ref['type'].decode('latin-1'))
    # Properties and frame.
    properties, associations = [], {}
    iprp = children.get(b'iprp', [None])[0]
    if iprp is not None:
        for child in iprp['children']:
            if child['type'] == b'ipco':
                properties = child['children']
            elif child['type'] == b'ipma':
                associations = parse_ipma(data, child)
    frame = None
    for index in associations.get(primary, ()):
        if 0 < index <= len(properties) and properties[index - 1]['type'] == b'ispe':
            at = properties[index - 1]['start'] + properties[index - 1]['header']
            if properties[index - 1]['end'] - at >= 12:
                frame = {'width': struct.unpack_from('>I', data, at + 4)[0], 'height': struct.unpack_from('>I', data, at + 8)[0]}
            break
    if frame is None:
        notes.append('heifNoIspe')
    if items[primary]['type'] in DERIVED:
        notes.append('heifDerivedPrimary')
    result['frame'] = frame
    result['primary'] = {'item': primary, 'type': (items[primary]['type'] or b'').decode('latin-1')}
    # Metadata slots by cdsc union to the primary image.
    cdsc = [r for r in refs if r['type'] == b'cdsc']
    slot_ids = set()
    for family, test, role in (('exif', lambda i: i['type'] == b'Exif', 'Exif item'), ('xmp', lambda i: i['type'] == b'mime' and i['contentType'] == XMP_TYPE, 'mime item')):
        candidates = [items[i] for i in order if i in items and test(items[i])]
        linked = [c for c in candidates if any(r['from'] == c['id'] and primary in r['to'] for r in cdsc)]
        for other in candidates:
            if other not in linked:
                notes.append('metadataForNonPrimaryItem:%d' % other['id'])
        slot_ids.update(c['id'] for c in linked)
        good, problem = [], []
        for c in linked:
            describes = {t for r in cdsc if r['from'] == c['id'] for t in r['to']}
            if describes - {primary}:
                common.refuse_write(result, 'HEIF_SHARED_METADATA_ITEM', 'item %d describes other images as well as the primary image' % c['id'], item=c['id'])
            if c['protection']:
                problem.append(('HEIF_PROTECTED_ITEM', c))
            elif c.get('unsupported'):
                problem.append((c['unsupported'], c))
            elif 'resolved' not in c or not c['resolved']:
                problem.append(('HEIF_REFERENCE_INVALID', c))
            elif c['implied']:
                problem.append(('HEIF_IMPLIED_EXTENT', c))
            else:
                payload = b''.join(bytes(data[p:p + n]) for p, n in c['resolved'])
                if family == 'exif':
                    skip = int.from_bytes(payload[:4], 'big') if len(payload) >= 4 else None
                    if skip is None or skip + 4 + 8 > len(payload) or not payloads.tiff_stream_ok(payload[4 + skip:]):
                        problem.append(('HEIF_EXIF_HEADER_INVALID', c))
                    else:
                        good.append(payload[4 + skip:])
                elif len(payload) > xmp.MAX_BYTES:
                    problem.append(('XMP_BOUND', c))
                else:
                    good.append(payload)
        result[family].extend(good)
        if not linked:
            result['slots'].append(common.slot(family, 'absent', role=role))
        elif len(linked) > 1:
            result['slots'].append(common.slot(family, 'ambiguous', role=role, count=len(linked)))
            common.refuse_write(result, 'HEIF_MULTIPLE_METADATA_ITEMS', 'the primary image has %d %s items' % (len(linked), family), family=family)
        elif problem:
            code, c = problem[0]
            state = 'unsupported' if code in ('HEIF_EXTERNAL_DATA', 'HEIF_ITEM_CONSTRUCTION_UNSUPPORTED') else 'unreadable'
            result['slots'].append(common.slot(family, state, role=role, count=1, code=code, message='item %d cannot be read: %s' % (c['id'], code), item=c['id']))
        else:
            result['slots'].append(common.slot(family, 'present', role=role, count=1, item=linked[0]['id']))
    result['slots'].append(common.slot('iptc', 'absent'))
    # Fingerprint.
    def add(role, key, begin, finish):
        result['protected'].append(common.entry(role, key, memoryview(data)[begin:finish]))
        result['ranges'].append((role, key, begin, finish - begin))
    add('heif/ftyp', 'ftyp', ftyp['start'], ftyp['end'])
    add('heif/hdlr', 'hdlr', hdlr['start'], hdlr['end'])
    add('heif/pitm', 'pitm', pitm_box['start'], pitm_box['end'])
    for ident in order:
        item = items[ident]
        if ident in slot_ids:
            continue
        add('heif/infe', str(ident), item['start'], item['end'])
        if item.get('resolved') is not None and not item.get('unsupported'):
            payload = b''.join(bytes(data[p:p + n]) for p, n in item['resolved'])
            result['protected'].append(common.entry('heif/item', str(ident), payload))
            for p, n in item['resolved']:
                result['ranges'].append(('heif/item', str(ident), p, n))
    if iprp is not None:
        add('heif/iprp', 'iprp', iprp['start'], iprp['end'])
    kept = [r for r in refs if not (r['type'] == b'cdsc' and r['from'] in slot_ids)]
    for index, ref in enumerate(kept):
        text = ('%s:%d:%s' % (ref['type'].decode('latin-1'), ref['from'], ','.join(str(t) for t in ref['to']))).encode()
        result['protected'].append(common.entry('heif/iref', str(index), text))
    counts = {}
    for child in meta['children']:
        if child['type'] in META_NAMED:
            continue
        name = child['type'].decode('latin-1')
        add('heif/meta', '%s#%d' % (name, counts.setdefault(name, 0)), child['start'], child['end'])
        counts[name] += 1
    counts = {}
    for box in top:
        if box['type'] in OTHER_TOP_SKIP:
            continue
        name = box['type'].decode('latin-1')
        add('heif/box', '%s#%d' % (name, counts.setdefault(name, 0)), box['start'], box['end'])
        counts[name] += 1
    # Bytes of mdat that no item references are not protected: say so.
    covered = sorted((p, p + n) for item in items.values() for p, n in item.get('resolved', ()) if n > 0)
    for box in top:
        if box['type'] != b'mdat':
            continue
        begin, finish = box['start'] + box['header'], box['end']
        used, position = 0, begin
        for a, b in covered:
            a, b = max(a, position), min(b, finish)
            if b > a:
                used += b - a
                position = b
        if used < finish - begin:
            notes.append('heifUnreferencedMdatBytesNotProtected')
            break
    result['slotRanges'] = [(i, p, n) for i in sorted(slot_ids) for p, n in items[i].get('resolved', ())]
    result['items'] = [{'id': i, 'type': (items[i]['type'] or b'').decode('latin-1'), 'hidden': items[i]['hidden'], 'protected': bool(items[i]['protection']),
                        'implied': bool(items[i].get('implied')), 'resolved': list(items[i].get('resolved', ()))} for i in order]
    return common.finish(result)
