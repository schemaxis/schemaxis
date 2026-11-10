"""WebP (RIFF) locator, VP8X outcome prediction and post-write layout proof (RFC 9649; standard library only).

``parse`` reads the chunk layout leniently and reports structural problems as data, so the same code can judge an input and a written
output. ``locate`` turns that layout into the common locator result: RIFF size faults are refused when the declared size exceeds the file
(the data cannot be trusted) and are write refusals when the file is longer than declared. Frame facts come from the VP8, VP8L and VP8X
headers only; no bitstream is decoded.

``predict_vp8x`` and ``prove_layout`` implement AM-16R. ExifTool 13.55 deletes VP8X only when no ANIM, ALPH, ICCP, EXIF or XMP chunk remains,
and otherwise keeps it with the E, X and I bits recomputed. The prediction may only narrow what is admitted; the proof of the written file
is authoritative and checks the layout, the E/X flags, every non-metadata chunk byte for byte (padding included), and the I, L, A flags
and canvas.
"""
import struct

from schemaxis.adaptors.exiftool import e5common as common, e5payloads as payloads, xmp

MAX_BYTES = 64 * 1024 * 1024
MAX_CHUNKS = 1024
EXIF_FLAG, XMP_FLAG, ICC_FLAG, ALPHA_FLAG, ANIM_FLAG = 0x08, 0x04, 0x20, 0x10, 0x02
METADATA = (b'EXIF', b'XMP ')
KEEPS_VP8X = (b'ANIM', b'ALPH', b'ICCP', b'EXIF', b'XMP ')
BITSTREAMS = (b'VP8 ', b'VP8L')


def parse(data):
    """``{'chunks': [{'id','offset','size','pad','padOk'}], 'problems': [(code, message)], 'end': int, ...}``; ``Refused`` only for non-WebP data."""
    refused = common.Refused
    if len(data) < 12 or data[:4] not in (b'RIFF', b'RF64') or data[8:12] != b'WEBP':
        raise refused('UNSUPPORTED_MEDIA', 'the file is not a RIFF WebP file')
    if data[:4] == b'RF64':
        raise refused('UNSUPPORTED_MEDIA', 'RF64 WebP files are not supported')
    declared = struct.unpack_from('<I', data, 4)[0]
    problems, found, position = [], [], 12
    limit = min(len(data), declared + 8)
    if declared + 8 > len(data):
        raise refused('RIFF_SIZE_MISMATCH', 'the RIFF size declares %d bytes but the file has %d' % (declared + 8, len(data)), declared=declared + 8, actual=len(data))
    if declared + 8 < len(data):
        problems.append(('RIFF_TRAILING_BYTES', 'the file has %d bytes after the declared RIFF size' % (len(data) - declared - 8)))
    if declared < 4:
        raise refused('INVALID_PHOTO_DATA', 'the RIFF size is too small')
    while position + 8 <= limit:
        if len(found) >= MAX_CHUNKS:
            raise refused('PHOTO_RESOURCE_LIMIT', 'the WebP has more than %d chunks' % MAX_CHUNKS)
        ident, size = struct.unpack_from('<4sI', data, position)
        padded = size + (size & 1)
        if position + 8 + padded > limit:
            raise refused('INVALID_PHOTO_DATA', 'a WebP chunk exceeds the RIFF size', chunk=ident.decode('latin-1'), offset=position)
        pad = bytes(data[position + 8 + size:position + 8 + padded])
        pad_ok = pad == b'\0' * (size & 1)
        if not pad_ok:
            problems.append(('RIFF_PADDING_INVALID', 'the %s chunk has a non-zero padding byte' % ident.decode('latin-1')))
        found.append({'id': ident, 'offset': position, 'size': size, 'pad': size & 1, 'padOk': pad_ok})
        position += 8 + padded
    if position != limit:
        raise refused('INVALID_PHOTO_DATA', 'the RIFF payload ends inside a chunk header', offset=position)
    return {'chunks': found, 'problems': problems, 'end': position, 'declared': declared}


def body(data, chunk):
    return memoryview(data)[chunk['offset'] + 8:chunk['offset'] + 8 + chunk['size']]


def whole(data, chunk):
    return memoryview(data)[chunk['offset']:chunk['offset'] + 8 + chunk['size'] + chunk['pad']]


def vp8_frame(payload):
    if len(payload) < 10 or payload[0] & 1 or bytes(payload[3:6]) != b'\x9d\x01\x2a':
        return None
    width, height = struct.unpack_from('<HH', payload, 6)
    return {'width': width & 0x3FFF, 'height': height & 0x3FFF}


def vp8l_frame(payload):
    if len(payload) < 5 or payload[0] != 0x2F:
        return None
    bits = struct.unpack_from('<I', payload, 1)[0]
    return {'width': (bits & 0x3FFF) + 1, 'height': ((bits >> 14) & 0x3FFF) + 1, 'alpha': bool((bits >> 28) & 1), 'version': bits >> 29}


def vp8x_facts(payload):
    if len(payload) < 10:
        return None
    return {'flags': payload[0], 'width': int.from_bytes(payload[4:7], 'little') + 1, 'height': int.from_bytes(payload[7:10], 'little') + 1}


def facts(data, layout):
    """Layout facts used by prediction and proof: chunk ids, VP8X flags and canvas, the bitstream chunk and its header facts."""
    ids = [c['id'] for c in layout['chunks']]
    out = {'ids': ids, 'vp8x': None, 'bitstream': None, 'alpha': False}
    for chunk in layout['chunks']:
        if chunk['id'] == b'VP8X' and out['vp8x'] is None:
            out['vp8x'] = vp8x_facts(body(data, chunk))
        elif chunk['id'] in BITSTREAMS and out['bitstream'] is None:
            payload = body(data, chunk)
            frame = vp8_frame(payload) if chunk['id'] == b'VP8 ' else vp8l_frame(payload)
            out['bitstream'] = {'id': chunk['id'], 'frame': frame}
            out['alpha'] = bool(frame and frame.get('alpha'))
    return out


def locate(data):
    layout = parse(data)
    result = common.new_result('webp')
    notes = result['notes']
    for code, message in layout['problems']:
        notes.append(code)
        common.refuse_write(result, code, message)
    chunks = layout['chunks']
    seen = facts(data, layout)
    ids = seen['ids']
    if not chunks:
        raise common.Refused('INVALID_PHOTO_DATA', 'the WebP has no chunks')
    vp8x = seen['vp8x']
    first = chunks[0]['id']
    if first == b'VP8X':
        if vp8x is None:
            raise common.Refused('INVALID_PHOTO_DATA', 'the VP8X chunk is shorter than 10 bytes')
        form = 'extended'
    elif first in BITSTREAMS:
        form = 'simple-lossy' if first == b'VP8 ' else 'simple-lossless'
    else:
        raise common.Refused('INVALID_PHOTO_DATA', 'the first WebP chunk is neither VP8X, VP8 nor VP8L')
    result['form'] = form
    if form != 'extended' and len(chunks) > 1:
        notes.append('webpChunksWithoutVp8x')
        common.refuse_write(result, 'WEBP_LAYOUT_UNSUPPORTED', 'the simple-format file carries chunks other than one bitstream')
    if form != 'extended':
        stream_chunk = chunks[0]
        if stream_chunk['size'] < (16 if first == b'VP8 ' else 6):
            notes.append('webpBitstreamHeaderShort')
            common.refuse_write(result, 'WEBP_BITSTREAM_HEADER_SHORT', 'the native writer reads %d bytes of the bitstream to size a created VP8X chunk' % (16 if first == b'VP8 ' else 6))
    if ids.count(b'VP8X') > 1:
        notes.append('webpDuplicateVp8x')
        common.refuse_write(result, 'WEBP_LAYOUT_UNSUPPORTED', 'the file has more than one VP8X chunk')
    animated = b'ANIM' in ids or bool(vp8x and vp8x['flags'] & ANIM_FLAG)
    stream = seen['bitstream']
    frame = None
    if stream is not None and stream['frame'] is None:
        raise common.Refused('INVALID_PHOTO_DATA', 'the %s chunk has no valid bitstream header' % stream['id'].decode().strip())
    if stream is not None:
        frame = {'width': stream['frame']['width'], 'height': stream['frame']['height'], 'bitstream': stream['id'].decode().strip()}
    if form == 'extended':
        if animated:
            notes.append('animated')
            frame = {'width': vp8x['width'], 'height': vp8x['height'], 'animated': True}
        elif stream is None:
            raise common.Refused('INVALID_PHOTO_DATA', 'a still extended WebP has no VP8 or VP8L bitstream')
        elif (vp8x['width'], vp8x['height']) != (frame['width'], frame['height']):
            notes.append('canvasBitstreamMismatch')
            common.refuse_write(result, 'WEBP_CANVAS_MISMATCH', 'the VP8X canvas differs from the bitstream size', canvas=[vp8x['width'], vp8x['height']],
                                bitstream=[frame['width'], frame['height']])
        frame['flags'] = vp8x['flags']
    result['frame'] = frame
    slot_chunks = {}
    for family, ident in (('exif', b'EXIF'), ('xmp', b'XMP ')):
        items = [c for c in chunks if c['id'] == ident]
        slot_chunks[family] = items
        good, bad = [], []
        for chunk in items:
            payload = bytes(body(data, chunk))
            if family == 'exif':
                if payload.startswith(payloads.EXIF_PREFIX):
                    notes.append('webpExifPrefix')
                    common.refuse_write(result, 'WEBP_EXIF_PREFIX_UNSUPPORTED', 'the EXIF chunk keeps a leading Exif header that the native writer would preserve')
                    payload = payload[len(payloads.EXIF_PREFIX):]
                if payloads.tiff_stream_ok(payload):
                    good.append(payload)
                else:
                    bad.append('INVALID_EXIF_STRUCTURE')
            elif len(payload) > xmp.MAX_BYTES:
                bad.append('XMP_BOUND')
            else:
                good.append(payload)
        result[family].extend(good)
        role = ident.decode()
        if not items:
            result['slots'].append(common.slot(family, 'absent', role=role if family != 'iptc' else None))
        elif len(items) > 1:
            result['slots'].append(common.slot(family, 'ambiguous', role=role, count=len(items)))
            common.refuse_write(result, 'WEBP_DUPLICATE_METADATA_CHUNK', 'the file has %d %s chunks' % (len(items), role.strip()), chunk=role.strip())
        elif bad:
            result['slots'].append(common.slot(family, 'unreadable', role=role, count=1, code=bad[0], message='the %s chunk cannot be read: %s' % (role.strip(), bad[0])))
        else:
            result['slots'].append(common.slot(family, 'present', role=role, count=1))
    result['slots'].append(common.slot('iptc', 'absent'))
    for chunk in chunks:
        if chunk['id'] in METADATA:
            continue
        if chunk['id'] == b'VP8X':
            masked = bytes([vp8x['flags'] & ~(EXIF_FLAG | XMP_FLAG)]) + bytes(body(data, chunk)[1:])
            result['protected'].append(common.entry('riff/vp8x', 'canvas+flags', masked + (b'\0' * chunk['pad'])))
            result['ranges'].append(('riff/vp8x', 'canvas+flags', chunk['offset'], 8 + chunk['size'] + chunk['pad']))
            continue
        index = sum(1 for earlier in chunks[:chunks.index(chunk)] if earlier['id'] == chunk['id'])
        key = '%s#%d' % (chunk['id'].decode('latin-1'), index)
        result['protected'].append(common.entry('riff/chunk', key, whole(data, chunk)))
        result['ranges'].append(('riff/chunk', key, chunk['offset'], 8 + chunk['size'] + chunk['pad']))
    result['slotRanges'] = [(c['id'].decode(), c['offset'], 8 + c['size'] + c['pad']) for c in chunks if c['id'] in METADATA]
    result['layout'] = {'form': form, 'ids': [i.decode('latin-1') for i in ids], 'vp8x': vp8x, 'alpha': seen['alpha']}
    return common.finish(result)


def predict_vp8x(layout_facts, delete=(b'EXIF', b'XMP ')):
    """AM-16R plan prediction for a plan that removes ``delete`` chunks: ``{'admitted': bool, 'vp8x': 'kept'|'removed'|'absent', 'code', 'reason'}``."""
    ids = layout_facts['ids']
    vp8x = layout_facts['vp8x']
    if b'VP8X' not in ids:
        return {'admitted': True, 'vp8x': 'absent', 'code': None, 'reason': None}
    remaining = [i for i in ids if i not in delete]
    if any(i in KEEPS_VP8X for i in remaining):
        return {'admitted': True, 'vp8x': 'kept', 'code': None, 'reason': None}
    rest = [i for i in remaining if i != b'VP8X']
    flags = vp8x['flags'] if vp8x else 0
    refused = {'admitted': False, 'vp8x': 'removed', 'code': 'WEBP_METADATA_REMOVAL_LAYOUT_UNSUPPORTED'}
    if rest not in ([b'VP8 '], [b'VP8L']):
        return dict(refused, reason='the chunks left after VP8X is removed are not exactly one VP8 or VP8L bitstream')
    if flags & (ICC_FLAG | ANIM_FLAG):
        return dict(refused, reason='the ICC or animation flag has no chunk carrying it')
    if flags & ALPHA_FLAG and not (rest == [b'VP8L'] and layout_facts['alpha']):
        return dict(refused, reason='the alpha flag would be the only carrier of the alpha fact')
    return {'admitted': True, 'vp8x': 'removed', 'code': None, 'reason': None}


def non_metadata(data, layout):
    """``[(id, bytes)]`` of every chunk except VP8X and the metadata chunks, padding included, in order."""
    return [(c['id'], bytes(whole(data, c))) for c in layout['chunks'] if c['id'] != b'VP8X' and c['id'] not in METADATA]


def prove_layout(before, after):
    """AM-16R post-write proof over two WebP byte strings; ``[{'code', 'message'}]`` (empty means the layout and preservation hold)."""
    faults = []
    try:
        old = parse(before)
        new = parse(after)
    except common.Refused as error:
        return [{'code': error.code, 'message': error.message}]
    for code, message in new['problems']:
        faults.append({'code': 'RIFF_SIZE_MISMATCH' if code == 'RIFF_TRAILING_BYTES' else code, 'message': message})
    old_facts, new_facts = facts(before, old), facts(after, new)
    if non_metadata(before, old) != non_metadata(after, new):
        faults.append({'code': 'PRESERVATION_MISMATCH', 'message': 'a non-metadata chunk changed, moved, was dropped or added'})
    ids = new_facts['ids']
    if b'VP8X' not in ids:
        if ids not in ([b'VP8 '], [b'VP8L']):
            faults.append({'code': 'WEBP_LAYOUT_INVALID_AFTER_WRITE', 'message': 'without VP8X the file must be exactly one VP8 or VP8L chunk'})
        elif old_facts['vp8x']:
            flags = old_facts['vp8x']['flags']
            if flags & (ICC_FLAG | ANIM_FLAG) or (flags & ALPHA_FLAG and not new_facts['alpha']):
                faults.append({'code': 'WEBP_LAYOUT_INVALID_AFTER_WRITE', 'message': 'VP8X removal lost the ICC, animation or alpha fact it carried'})
        return faults
    if ids[0] != b'VP8X' or ids.count(b'VP8X') != 1:
        faults.append({'code': 'WEBP_LAYOUT_INVALID_AFTER_WRITE', 'message': 'VP8X must be the first and only VP8X chunk'})
        return faults
    new_x = new_facts['vp8x']
    if new_x is None:
        faults.append({'code': 'WEBP_LAYOUT_INVALID_AFTER_WRITE', 'message': 'the VP8X chunk is truncated'})
        return faults
    flags = new_x['flags']
    if bool(flags & EXIF_FLAG) != (b'EXIF' in ids) or bool(flags & XMP_FLAG) != (b'XMP ' in ids):
        faults.append({'code': 'WEBP_FLAGS_INCONSISTENT', 'message': 'the VP8X E or X flag disagrees with the EXIF or XMP chunk'})
    if old_facts['vp8x']:
        old_x = old_facts['vp8x']
        if (old_x['flags'] & (ICC_FLAG | ALPHA_FLAG | ANIM_FLAG)) != (flags & (ICC_FLAG | ALPHA_FLAG | ANIM_FLAG)) or (old_x['width'], old_x['height']) != (new_x['width'], new_x['height']):
            faults.append({'code': 'PRESERVATION_MISMATCH', 'message': 'the VP8X I, L or A flag or the canvas changed'})
    else:
        stream = new_facts['bitstream']
        frame = stream['frame'] if stream else None
        allowed = EXIF_FLAG | XMP_FLAG | (ALPHA_FLAG if new_facts['alpha'] else 0)
        if frame is None or (new_x['width'], new_x['height']) != (frame['width'], frame['height']) or flags & ~allowed:
            faults.append({'code': 'PRESERVATION_MISMATCH', 'message': 'a created VP8X must carry the bitstream size and only the E, X and bitstream alpha flags'})
    return faults
