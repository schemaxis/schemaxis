"""PNG locator (PNG Third Edition chunk structure; standard library only).

Chunks are ``length(4) type(4) data crc(4)``. Every CRC is verified, because a damaged chunk cannot be told from a deliberately altered one:
a bad CRC makes the whole file unreadable (``PNG_CRC_INVALID``). Structure faults that leave the metadata readable (a chunk after IEND,
metadata after the first IDAT, repeated single-instance chunks, legacy ``Raw profile type`` text) are read notes and precise write
refusals. Metadata slots are the ``eXIf`` chunk and the iTXt chunk ``XML:com.adobe.xmp``; legacy raw-profile text is readable but never written.

The fingerprint holds every other chunk as a whole (length, type, data and CRC) in file order, one row per chunk, so IDAT splits, rendering
chunks (gAMA, cHRM, sRGB, iCCP, cICP, mDCV, cLLI, sBIT, tRNS, bKGD, pHYs), animation chunks and private chunks are all protected. Text
chunks have their own role so a removal category that selects them by keyword can declare exactly those rows changeable.
"""
import struct
import zlib

from schemaxis.adaptors.exiftool import e5common as common, e5payloads as payloads, xmp

SIGNATURE = b'\x89PNG\r\n\x1a\n'
MAX_BYTES = 64 * 1024 * 1024
MAX_CHUNKS = 4096
MAX_CHUNK = 2 ** 31 - 1
XMP_KEYWORD = b'XML:com.adobe.xmp'
TEXT = (b'tEXt', b'zTXt', b'iTXt')
SINGLE = (b'IHDR', b'PLTE', b'IEND', b'gAMA', b'cHRM', b'sRGB', b'iCCP', b'sBIT', b'bKGD', b'hIST', b'tRNS', b'pHYs', b'tIME', b'cICP', b'mDCV',
          b'cLLI', b'eXIf', b'acTL')
RENDER = ('PLTE', 'tRNS', 'gAMA', 'cHRM', 'sRGB', 'iCCP', 'cICP', 'mDCV', 'cLLI', 'sBIT', 'bKGD', 'pHYs')
COLOUR_TYPES = {0: 'grayscale', 2: 'truecolour', 3: 'indexed', 4: 'grayscale-alpha', 6: 'truecolour-alpha'}
RAW_NAMES = {'exif': 'exif', 'APP1': 'exif', 'xmp': 'xmp', 'iptc': 'iptc'}


def chunks(data):
    """``[(type, offset, length)]`` for a CRC-valid, ordered, bounded chunk stream; ``Refused`` for anything that cannot be trusted."""
    refused = common.Refused
    if len(data) < 8 or data[:8] != SIGNATURE:
        raise refused('UNSUPPORTED_MEDIA', 'the file does not start with the PNG signature')
    found, position = [], 8
    while True:
        if position + 12 > len(data):
            raise refused('INVALID_PHOTO_DATA', 'the PNG ends inside a chunk header or without an IEND chunk', offset=position)
        length, kind = struct.unpack_from('>I4s', data, position)
        if len(found) >= MAX_CHUNKS:
            raise refused('PHOTO_RESOURCE_LIMIT', 'the PNG has more than %d chunks' % MAX_CHUNKS)
        if length > MAX_CHUNK or position + 12 + length > len(data):
            raise refused('INVALID_PHOTO_DATA', 'a PNG chunk length is invalid or exceeds the file', chunk=kind.decode('latin-1'), offset=position)
        if not all(65 <= b <= 90 or 97 <= b <= 122 for b in kind):
            raise refused('INVALID_PHOTO_DATA', 'a PNG chunk type is not four ASCII letters', offset=position)
        stored = struct.unpack_from('>I', data, position + 8 + length)[0]
        if zlib.crc32(memoryview(data)[position + 4:position + 8 + length]) & 0xFFFFFFFF != stored:
            raise refused('PNG_CRC_INVALID', 'the %s chunk fails its CRC' % kind.decode('latin-1'), chunk=kind.decode('latin-1'), offset=position)
        found.append((kind, position, length))
        position += 12 + length
        if kind == b'IEND':
            return found, position


def itxt(body):
    """``(keyword, compressed, text_bytes_or_stream)`` of an iTXt body, or ``None`` when it is malformed."""
    end = body.find(b'\0')
    if end < 1 or end > 79 or len(body) < end + 5:
        return None
    flag, method = body[end + 1], body[end + 2]
    tag_end = body.find(b'\0', end + 3)
    if tag_end < 0:
        return None
    translated_end = body.find(b'\0', tag_end + 1)
    if translated_end < 0:
        return None
    return body[:end], (flag, method), body[translated_end + 1:]


def locate(data):
    found, end = chunks(data)
    view = memoryview(data)
    result = common.new_result('png')
    notes = result['notes']
    if end != len(data):
        notes.append('PNG_TRAILING_BYTES')
        common.refuse_write(result, 'PNG_TRAILING_BYTES', 'the file has %d bytes after IEND' % (len(data) - end), bytes=len(data) - end)
    first_kind, first_at, first_length = found[0]
    if first_kind != b'IHDR' or first_length != 13:
        raise common.Refused('INVALID_PHOTO_DATA', 'the first PNG chunk is not a 13-byte IHDR')
    width, height, depth, colour, _, _, interlace = struct.unpack_from('>IIBBBBB', data, first_at + 8)
    result['frame'] = {'width': width, 'height': height, 'bitDepth': depth, 'colourType': COLOUR_TYPES.get(colour, 'unknown'), 'interlaced': bool(interlace)}
    types = [c[0] for c in found]
    first_idat = types.index(b'IDAT') if b'IDAT' in types else None
    result['render'] = [name for name in RENDER if name.encode() in types]
    if b'acTL' in types:
        notes.append('apng')
        result['frame']['animationFrames'] = struct.unpack_from('>I', data, found[types.index(b'acTL')][1] + 8)[0]
    if first_idat is None:
        notes.append('png-without-idat')
    idats = [i for i, k in enumerate(types) if k == b'IDAT']
    if idats and idats != list(range(idats[0], idats[0] + len(idats))):
        common.refuse_write(result, 'PNG_CHUNK_ORDER_INVALID', 'the IDAT chunks are not consecutive')
    if b'PLTE' in types and first_idat is not None and types.index(b'PLTE') > first_idat:
        common.refuse_write(result, 'PNG_CHUNK_ORDER_INVALID', 'PLTE follows the first IDAT')
    for kind in SINGLE:
        if types.count(kind) > 1 and kind != b'eXIf':
            notes.append('pngDuplicateChunk:' + kind.decode())
            common.refuse_write(result, 'PNG_DUPLICATE_CHUNK', 'the %s chunk appears %d times' % (kind.decode(), types.count(kind)), chunk=kind.decode())
    slots = {'exif': [], 'xmp': [], 'iptc': []}        # (state, payload|None, code|None, role, index)
    slot_chunks = set()
    after_idat = False
    for index, (kind, at, length) in enumerate(found):
        body = view[at + 8:at + 8 + length]
        placed_late = first_idat is not None and index > first_idat
        if kind == b'eXIf':
            slot_chunks.add(index)
            after_idat |= placed_late
            if payloads.tiff_stream_ok(body):
                slots['exif'].append(('present', bytes(body), None, 'eXIf', index))
            else:
                slots['exif'].append(('unreadable', None, 'INVALID_EXIF_STRUCTURE', 'eXIf', index))
        elif kind == b'iTXt':
            if bytes(body[:len(XMP_KEYWORD) + 1]) != XMP_KEYWORD + b'\0':
                continue
            parsed = itxt(bytes(body))
            if parsed is None:
                slot_chunks.add(index)
                slots['xmp'].append(('unreadable', None, 'XMP_MALFORMED', 'iTXt:XML:com.adobe.xmp', index))
                continue
            _, (flag, method), text = parsed
            slot_chunks.add(index)
            after_idat |= placed_late
            try:
                if flag == 1:
                    if method != 0:
                        raise payloads.Problem('XMP_MALFORMED', 'an iTXt chunk declares an unknown compression method')
                    text = payloads.inflate_bounded(text, xmp.MAX_BYTES)
                elif flag != 0:
                    raise payloads.Problem('XMP_MALFORMED', 'an iTXt chunk has an invalid compression flag')
                elif len(text) > xmp.MAX_BYTES:
                    raise payloads.Problem('XMP_BOUND', 'XMP packet exceeds %d bytes' % xmp.MAX_BYTES)
                slots['xmp'].append(('present', bytes(text), None, 'iTXt:XML:com.adobe.xmp', index))
            except payloads.Problem as problem:
                slots['xmp'].append(('unreadable', None, problem.code, 'iTXt:XML:com.adobe.xmp', index))
        elif kind in (b'tEXt', b'zTXt'):
            end = bytes(body[:80]).find(b'\0')
            keyword = bytes(body[:end]) if end > 0 else b''
            if not keyword.startswith(payloads.RAW_PROFILE):
                continue
            try:
                text = bytes(body[end + 1:]) if kind == b'tEXt' else payloads.inflate_bounded(bytes(body[end + 2:]), payloads.MAX_PROFILE_TEXT)
            except payloads.Problem:
                notes.append('pngLegacyRawProfileUndecoded')
                continue
            decoded = payloads.raw_profile(text)
            family = RAW_NAMES.get(decoded[0]) if decoded else None
            if decoded is None or family is None:
                notes.append('pngLegacyRawProfileUndecoded')
                continue
            payload = decoded[1]
            if family == 'exif' and payload.startswith(payloads.EXIF_PREFIX):
                payload = payload[len(payloads.EXIF_PREFIX):]
            elif family == 'exif' and payload.startswith(payloads.XMP_PREFIX):
                family, payload = 'xmp', payload[len(payloads.XMP_PREFIX):]
            if family == 'iptc':
                if not payload.startswith(b'8BIM'):
                    notes.append('pngLegacyRawProfileUndecoded')
                    continue
                payload = payloads.photoshop_body_from_resources(payload)
            slots[family].append(('present', payload, None, 'legacyRawProfile', index))
            notes.append('pngLegacyRawProfile')
            common.refuse_write(result, 'PNG_LEGACY_RAW_PROFILE', 'legacy raw-profile text carries %s; its conversion is not supported' % family, family=family)
    if after_idat:
        notes.append('pngMetadataAfterIdat')
        common.refuse_write(result, 'PNG_METADATA_AFTER_IDAT', 'a metadata chunk follows the first IDAT')
    if types.count(b'eXIf') > 1:
        notes.append('pngDuplicateChunk:eXIf')
    for family in common.FAMILIES:
        items = slots[family]
        good = [p for state, p, *_ in items if state == 'present']
        result[family].extend(good)
        if not items:
            result['slots'].append(common.slot(family, 'absent', role={'exif': 'eXIf', 'xmp': 'iTXt:XML:com.adobe.xmp', 'iptc': None}[family]))
        elif len(items) > 1:
            result['slots'].append(common.slot(family, 'ambiguous', role=items[0][3], count=len(items)))
        elif items[0][0] == 'present':
            result['slots'].append(common.slot(family, 'present', role=items[0][3], count=1))
        else:
            result['slots'].append(common.slot(family, 'unreadable', role=items[0][3], count=1, code=items[0][2], message='the %s slot cannot be read: %s' % (family, items[0][2])))
    if len([row for row in slots['exif'] if row[3] == 'eXIf']) > 1:
        common.refuse_write(result, 'PNG_DUPLICATE_CHUNK', 'more than one eXIf chunk', chunk='eXIf')
    if len([row for row in slots['xmp'] if row[3] != 'legacyRawProfile']) > 1:
        common.refuse_write(result, 'PNG_DUPLICATE_CHUNK', 'more than one XMP iTXt chunk', chunk='iTXt:XML:com.adobe.xmp')
    counts = {}
    for index, (kind, at, length) in enumerate(found):
        if index in slot_chunks:
            continue
        name = kind.decode('latin-1')
        if kind in TEXT:
            body = bytes(view[at + 8:at + 8 + min(length, 80)])
            keyword = body[:body.find(b'\0')].decode('latin-1') if b'\0' in body else name
            role, key = 'png/text', '%s:%s#%d' % (name, keyword, counts.get((name, keyword), 0))
            counts[(name, keyword)] = counts.get((name, keyword), 0) + 1
        else:
            role = 'png/critical' if kind[0] < 97 else 'png/ancillary'
            key = '%s#%d' % (name, counts.get(name, 0))
            counts[name] = counts.get(name, 0) + 1
        span = view[at:at + 12 + length]
        result['protected'].append(common.entry(role, key, span))
        result['ranges'].append((role, key, at, 12 + length))
    result['slotRanges'] = [(i, found[i][1], 12 + found[i][2]) for i in sorted(slot_chunks)]
    return common.finish(result)
