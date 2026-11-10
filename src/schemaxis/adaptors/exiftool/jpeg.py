"""Independent bounded reader for one baseline JPEG and its selected EXIF fields (standard library only).

This is the host oracle: it admits a photo before any native process starts and later recomputes what ExifTool must
have reported. It never calls ExifTool, never reads filesystem times and never decodes pixels: the JPEG entropy data is
only scanned for a well-formed end (stuffed bytes, restart markers, one EOI at the very end), so a successful parse
certifies marker/length structure and nothing about image quality. Only these fields are read: SOF width/height and
sampling facts, IFD0 Make/Model/Orientation, ExifIFD DateTimeOriginal/OffsetTimeOriginal. Everything else is unassessed.
"""
import re
import struct

from schemaxis.errors import fail

MAX_BYTES = 8 * 1024 * 1024
MAX_SEGMENTS = 128
MAX_IFD_ENTRIES = 256
MAX_STRING = 64
APP1 = 0xE1
SOF_MARKERS = frozenset(range(0xC0, 0xD0)) - {0xC4, 0xC8, 0xCC}
TAGS0 = {0x010F: 'make', 0x0110: 'model', 0x0112: 'orientation', 0x8769: 'exif'}
TAGS_EXIF = {0x9003: 'original', 0x9011: 'offset'}
DISPLAY = {'make': 'Make', 'model': 'Model', 'orientation': 'Orientation', 'exif': 'ExifOffset', 'original': 'DateTimeOriginal', 'offset': 'OffsetTimeOriginal'}
DATE = re.compile(r'(\d{4}):(\d{2}):(\d{2}) (\d{2}):(\d{2}):(\d{2})')
OFFSET = re.compile(r'([+-])(\d{2}):(\d{2})')
CODE = 'INVALID_PHOTO_DATA'


def refuse(code, message, at, photo, **observed):
    fail(code, message, at, photo=photo, **observed)


def leap(year):
    return year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)


def check_date(text, at, photo):
    """Exact EXIF ``YYYY:MM:DD HH:MM:SS`` with calendar validity; returns the integer parts."""
    match = DATE.fullmatch(text)
    if not match:
        refuse('INVALID_EXIF_VALUE', 'ExifIFD:DateTimeOriginal must be exactly YYYY:MM:DD HH:MM:SS in ASCII digits', at, photo, field='ExifIFD:DateTimeOriginal', value=text[:32])
    year, month, day, hour, minute, second = map(int, match.groups())
    days = (31, 29 if leap(year) else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)
    if not (1900 <= year <= 2100 and 1 <= month <= 12 and 1 <= day <= days[month - 1] and hour < 24 and minute < 60 and second < 60):
        refuse('INVALID_EXIF_VALUE', 'ExifIFD:DateTimeOriginal is not a valid calendar date and time between 1900 and 2100', at, photo, field='ExifIFD:DateTimeOriginal', value=text)
    return year, month, day, hour, minute, second


def check_offset(text, at, photo):
    """EXIF ``+HH:MM`` / ``-HH:MM`` between -14:00 and +14:00; returns signed minutes."""
    match = OFFSET.fullmatch(text)
    if not match:
        refuse('INVALID_EXIF_VALUE', 'ExifIFD:OffsetTimeOriginal must be exactly +HH:MM or -HH:MM', at, photo, field='ExifIFD:OffsetTimeOriginal', value=text[:32])
    sign, hours, minutes = match.group(1), int(match.group(2)), int(match.group(3))
    total = hours * 60 + minutes
    if sign == '-' and total == 0:
        refuse('INVALID_EXIF_VALUE', 'ExifIFD:OffsetTimeOriginal -00:00 means an unknown offset (RFC 3339) and is refused rather than published as UTC; +00:00 is the recorded zero offset', at, photo, field='ExifIFD:OffsetTimeOriginal', value=text)
    if minutes > 59 or total > 14 * 60 or (sign == '-' and total > 12 * 60):
        refuse('INVALID_EXIF_VALUE', 'ExifIFD:OffsetTimeOriginal is outside the offsets -12:00 to +14:00 or has minutes above 59', at, photo, field='ExifIFD:OffsetTimeOriginal', value=text)
    return -total if sign == '-' else total


def text_value(raw, field, at, photo):
    """One NUL-terminated printable-ASCII string; leading/trailing blanks and empty text are refused, not normalized."""
    if raw[-1:] != b'\0' or b'\0' in raw[:-1]:
        refuse('INVALID_EXIF_VALUE', field + ' must be one NUL-terminated ASCII string filling its count', at, photo, field=field)
    body = raw[:-1]
    if not body or len(body) > MAX_STRING or any(not 0x20 <= b <= 0x7E for b in body):
        refuse('INVALID_EXIF_VALUE', f'{field} must be 1 to {MAX_STRING} printable ASCII characters', at, photo, field=field, bytes=len(body))
    text = body.decode('ascii')
    if text != text.strip(' '):
        refuse('INVALID_EXIF_VALUE', field + ' has leading or trailing blanks, which are not normalized', at, photo, field=field)
    return text


def read_ifd(tiff, offset, kinds, order, at, photo, group, visited):
    """Selected entries of one IFD as {name: (type, count, value-bytes)}; duplicate selected tags are refused."""
    if offset < 8 or offset + 2 > len(tiff) or offset in visited:
        refuse('INVALID_EXIF_STRUCTURE', group + ' offset is outside the TIFF data, inside its header or repeats an earlier IFD', at, photo, field=group, offset=offset)
    visited.add(offset)
    count = struct.unpack_from(order + 'H', tiff, offset)[0]
    end = offset + 2 + 12 * count + 4
    if count > MAX_IFD_ENTRIES or end > len(tiff):
        refuse('INVALID_EXIF_STRUCTURE', group + ' entry table is truncated or exceeds the entry budget', at, photo, field=group, entries=count)
    found = {}
    for index in range(count):
        base = offset + 2 + 12 * index
        tag, kind, number = struct.unpack_from(order + 'HHI', tiff, base)
        name = kinds.get(tag)
        if name is None:
            continue
        if name in found:
            refuse('DUPLICATE_EXIF_TAG', f'{group} repeats selected tag 0x{tag:04X}; the observation would be ambiguous', at, photo, field=group + ':' + DISPLAY[name], tag=tag)
        size = {2: 1, 3: 2, 4: 4}.get(kind)
        if size is None or number == 0:
            refuse('INVALID_EXIF_VALUE', f'{group}:{DISPLAY[name]} has an unsupported type or a zero count', at, photo, field=group + ':' + DISPLAY[name], type=kind, count=number)
        length = size * number
        if length <= 4:
            raw = tiff[base + 8:base + 8 + length]
        else:
            where = struct.unpack_from(order + 'I', tiff, base + 8)[0]
            if where < 8 or where + length > len(tiff):
                refuse('INVALID_EXIF_STRUCTURE', f'{group}:{DISPLAY[name]} value lies outside the TIFF data', at, photo, field=group + ':' + DISPLAY[name], offset=where, bytes=length)
            raw = tiff[where:where + length]
        found[name] = (kind, number, raw)
    return found, struct.unpack_from(order + 'I', tiff, end - 4)[0]


def read_exif(payload, at, photo):
    tiff = payload[6:]
    if len(tiff) < 8 or tiff[:4] not in (b'II*\0', b'MM\0*'):
        refuse('INVALID_EXIF_STRUCTURE', 'Exif segment has no valid TIFF byte-order header', at, photo, field='TIFF')
    order = '<' if tiff[:2] == b'II' else '>'
    visited = set()
    first = struct.unpack_from(order + 'I', tiff, 4)[0]
    entries, following = read_ifd(tiff, first, TAGS0, order, at, photo, 'IFD0', visited)
    if following:  # IFD1 is not read; only the chain structure is bounded and cycle-checked
        if following in visited or following < 8 or following + 2 > len(tiff):
            refuse('INVALID_EXIF_STRUCTURE', 'IFD chain repeats an IFD or points outside the TIFF data', at, photo, field='IFD0')
        visited.add(following)
        chained = struct.unpack_from(order + 'I', tiff, following + 2 + 12 * struct.unpack_from(order + 'H', tiff, following)[0])[0] \
            if following + 2 + 12 * struct.unpack_from(order + 'H', tiff, following)[0] + 4 <= len(tiff) else None
        if chained is None or chained:
            refuse('INVALID_EXIF_STRUCTURE', 'IFD chain is longer than IFD0 and IFD1, truncated or cyclic', at, photo, field='IFD0')
    result = dict.fromkeys(('make', 'model', 'orientation', 'original', 'offset'))
    for name in ('make', 'model'):
        if name in entries:
            kind, number, raw = entries[name]
            if kind != 2:
                refuse('INVALID_EXIF_VALUE', 'IFD0:' + name.capitalize() + ' must be an ASCII value', at, photo, field='IFD0:' + name.capitalize(), type=kind)
            result[name] = text_value(raw, 'IFD0:' + name.capitalize(), at, photo)
    if 'orientation' in entries:
        kind, number, raw = entries['orientation']
        value = struct.unpack(order + 'H', raw)[0] if kind == 3 and number == 1 else None
        if value is None or not 1 <= value <= 8:
            refuse('INVALID_EXIF_VALUE', 'IFD0:Orientation must be one SHORT code from 1 to 8', at, photo, field='IFD0:Orientation', type=kind, count=number)
        result['orientation'] = value
    if 'exif' in entries:
        kind, number, raw = entries['exif']
        if kind != 4 or number != 1:
            refuse('INVALID_EXIF_STRUCTURE', 'the ExifIFD pointer must be one LONG', at, photo, field='IFD0:ExifOffset', type=kind, count=number)
        selected, _ = read_ifd(tiff, struct.unpack(order + 'I', raw)[0], TAGS_EXIF, order, at, photo, 'ExifIFD', visited)
        for name, length in (('original', 20), ('offset', 7)):
            if name in selected:
                kind, number, raw = selected[name]
                field = 'ExifIFD:' + ('DateTimeOriginal' if name == 'original' else 'OffsetTimeOriginal')
                if kind != 2 or number != length:
                    refuse('INVALID_EXIF_VALUE', f'{field} must be ASCII with count {length}', at, photo, field=field, type=kind, count=number)
                result[name] = text_value(raw, field, at, photo)
        if result['original'] is not None:
            check_date(result['original'], at, photo)
        if result['offset'] is not None:
            check_offset(result['offset'], at, photo)
    result['byteOrder'] = 'little-endian' if order == '<' else 'big-endian'
    return result


def parse(data, at='$.photos[0].path', photo='photo'):
    """Validate the whole file structure and return its selected facts (width, height, EXIF subset)."""
    if len(data) > MAX_BYTES:
        refuse('PHOTO_RESOURCE_LIMIT', f'photo exceeds {MAX_BYTES} bytes', at, photo, bytes=len(data))
    if data[:2] != b'\xff\xd8':
        refuse(CODE, 'expected a JPEG file starting with SOI', at, photo)
    position, segments, frame, exif, scanned = 2, 0, None, None, False
    while True:
        while position < len(data) and data[position] == 0xFF and position + 1 < len(data) and data[position + 1] == 0xFF:
            position += 1
        if position + 4 > len(data) or data[position] != 0xFF:
            refuse(CODE, 'JPEG marker structure is truncated or malformed', at, photo, offset=position)
        marker = data[position + 1]
        if marker == 0xD9:
            refuse(CODE, 'JPEG ends before any scan', at, photo)
        length = struct.unpack_from('>H', data, position + 2)[0]
        segments += 1
        if segments > MAX_SEGMENTS or length < 2 or position + 2 + length > len(data):
            refuse(CODE, 'JPEG segment length is invalid, truncated or exceeds the segment budget', at, photo, marker=marker)
        body = data[position + 4:position + 2 + length]
        position += 2 + length
        if marker in SOF_MARKERS:
            if marker != 0xC0:
                refuse('UNSUPPORTED_JPEG', 'only baseline sequential DCT (SOF0) JPEG is supported; progressive, extended, lossless and arithmetic coding are refused', at, photo, marker=marker)
            if frame is not None:
                refuse('UNSUPPORTED_JPEG', 'multiple JPEG frames are unsupported', at, photo)
            if len(body) != 15 or body[0] != 8 or body[5] != 3:
                refuse('UNSUPPORTED_JPEG', 'only 8-bit three-component baseline JPEG is supported', at, photo, precision=body[0] if body else None)
            height, width = struct.unpack_from('>HH', body, 1)
            if not width or not height:
                refuse(CODE, 'JPEG frame dimensions must be positive (a zero height defers to DNL, which is unsupported)', at, photo, width=width, height=height)
            frame = (width, height)
        elif marker == 0xDA:
            if frame is None or len(body) != 10 or body[0] != 3:
                refuse(CODE, 'JPEG scan appears without a matching three-component frame', at, photo)
            if scanned:
                refuse('UNSUPPORTED_JPEG', 'multiple scans are unsupported', at, photo)
            scanned = True
            break
        elif marker == APP1 and body[:6] == b'Exif\0\0':
            if exif is not None:
                refuse('AMBIGUOUS_EXIF', 'more than one Exif APP1 segment makes the observation ambiguous', at, photo)
            exif = body
        elif not (0xE0 <= marker <= 0xEF or marker in (0xDB, 0xC4, 0xDD, 0xFE)):
            refuse('UNSUPPORTED_JPEG', f'JPEG marker 0xFF{marker:02X} is outside the supported baseline structure', at, photo, marker=marker)
    while position < len(data):  # entropy-coded data: stuffed FF00, restart markers, then exactly one final EOI
        if data[position] != 0xFF:
            position += 1
            continue
        following = data[position + 1] if position + 1 < len(data) else None
        if following == 0 or following is not None and 0xD0 <= following <= 0xD7:
            position += 2
        elif following == 0xD9 and position + 2 == len(data):
            break
        else:
            refuse('UNSUPPORTED_JPEG', 'scan data is followed by a marker other than the final EOI, or bytes follow EOI (multi-image or trailer data is unsupported)', at, photo, offset=position)
    else:
        refuse(CODE, 'JPEG is truncated: no final EOI', at, photo)
    selected = read_exif(exif, at, photo) if exif is not None else dict.fromkeys(('make', 'model', 'orientation', 'original', 'offset'))
    return {'width': frame[0], 'height': frame[1], **selected}


def utc_text(local, offset_minutes):
    """Exact UTC arithmetic from the recorded wall time and offset: 'YYYY-MM-DDTHH:MM:SSZ'."""
    year, month, day, hour, minute, second = check_date(local, '$', 'utc')
    days = [31, 29 if leap(year) else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    total = hour * 60 + minute - offset_minutes
    day += total // 1440
    total %= 1440
    while day < 1:
        month -= 1
        if month < 1:
            year, month, days[1] = year - 1, 12, 29 if leap(year - 1) else 28
        day += days[month - 1]
    while day > days[month - 1]:
        day -= days[month - 1]
        month += 1
        if month > 12:
            year, month, days[1] = year + 1, 1, 29 if leap(year + 1) else 28
    return f'{year:04d}-{month:02d}-{day:02d}T{total // 60:02d}:{total % 60:02d}:{second:02d}Z'


def local_text(local):
    year, month, day, hour, minute, second = check_date(local, '$', 'local')
    return f'{year:04d}-{month:02d}-{day:02d}T{hour:02d}:{minute:02d}:{second:02d}'
