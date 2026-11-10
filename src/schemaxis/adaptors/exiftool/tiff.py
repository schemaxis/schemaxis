"""Shared bounded TIFF/EXIF IFD walker (standard library only).

One walker serves every container that carries a TIFF payload. It returns raw typed entries per IFD (IFD0, ExifIFD, GPS, IFD1) and
never interprets a value: catalogue-driven codecs do that. Duplicate tags are kept, so ambiguity is reported rather than lost. A damaged
IFD is reported for that IFD only; the other IFDs of the payload stay readable.
"""
import struct

MAX_ENTRIES = 1024
MAX_VALUE_BYTES = 65536
MAX_TOTAL_VALUE_BYTES = 4 * 1024 * 1024
TYPES = {1: ('BYTE', 1), 2: ('ASCII', 1), 3: ('SHORT', 2), 4: ('LONG', 4), 5: ('RATIONAL', 8), 6: ('SBYTE', 1), 7: ('UNDEFINED', 1),
         8: ('SSHORT', 2), 9: ('SLONG', 4), 10: ('SRATIONAL', 8), 11: ('FLOAT', 4), 12: ('DOUBLE', 8)}
POINTERS = {0x8769: 'ExifIFD', 0x8825: 'GPS'}


class Entry:
    __slots__ = ('tag', 'kind', 'count', 'raw', 'order', 'oversize')

    def __init__(self, tag, kind, count, raw, order, oversize=False):
        self.tag, self.kind, self.count, self.raw, self.order, self.oversize = tag, kind, count, raw, order, oversize

    def values(self):
        """Numeric values for integer, rational and floating types; ``None`` when the type or length is not numeric."""
        name = TYPES.get(self.kind, ('?', 0))[0]
        if self.raw is None or name not in ('BYTE', 'SHORT', 'LONG', 'SBYTE', 'SSHORT', 'SLONG', 'RATIONAL', 'SRATIONAL', 'FLOAT', 'DOUBLE'):
            return None
        o = self.order
        fmt = {'BYTE': 'B', 'SHORT': 'H', 'LONG': 'I', 'SBYTE': 'b', 'SSHORT': 'h', 'SLONG': 'i', 'FLOAT': 'f', 'DOUBLE': 'd'}.get(name)
        if fmt:
            return list(struct.unpack(o + fmt * self.count, self.raw))
        unit = 'II' if name == 'RATIONAL' else 'ii'
        flat = struct.unpack(o + unit * self.count, self.raw)
        return [(flat[i], flat[i + 1]) for i in range(0, len(flat), 2)]


class Damaged(Exception):
    def __init__(self, code, message, **observed):
        super().__init__(message)
        self.code, self.message, self.observed = code, message, observed


def header(tiff):
    if len(tiff) < 8 or tiff[:4] not in (b'II*\0', b'MM\0*'):
        raise Damaged('INVALID_EXIF_STRUCTURE', 'the payload has no valid TIFF byte-order header')
    order = '<' if tiff[:2] == b'II' else '>'
    return order, struct.unpack_from(order + 'I', tiff, 4)[0]


def read_ifd(tiff, offset, order, budget):
    """All entries of one IFD as a list (duplicates kept) plus the next-IFD offset."""
    if offset < 8 or offset + 2 > len(tiff):
        raise Damaged('INVALID_EXIF_STRUCTURE', 'an IFD offset lies outside the TIFF data or inside its header', offset=offset)
    count = struct.unpack_from(order + 'H', tiff, offset)[0]
    end = offset + 2 + 12 * count + 4
    if count > MAX_ENTRIES or end > len(tiff):
        raise Damaged('INVALID_EXIF_STRUCTURE', 'an IFD entry table is truncated or exceeds the entry budget', entries=count)
    entries = []
    for index in range(count):
        base = offset + 2 + 12 * index
        tag, kind, number = struct.unpack_from(order + 'HHI', tiff, base)
        size = TYPES.get(kind, (None, 0))[1]
        length = size * number
        if not size:
            entries.append(Entry(tag, kind, number, None, order, False))
            continue
        if length <= 4:
            raw = tiff[base + 8:base + 8 + length]
        else:
            where = struct.unpack_from(order + 'I', tiff, base + 8)[0]
            if where < 8 or where + length > len(tiff):
                raise Damaged('INVALID_EXIF_STRUCTURE', 'an IFD value lies outside the TIFF data', tag=tag, offset=where, bytes=length)
            if length > MAX_VALUE_BYTES or budget[0] + length > MAX_TOTAL_VALUE_BYTES:
                entries.append(Entry(tag, kind, number, None, order, True))
                continue
            budget[0] += length
            raw = tiff[where:where + length]
        entries.append(Entry(tag, kind, number, raw, order))
    return entries, struct.unpack_from(order + 'I', tiff, end - 4)[0]


def walk(tiff):
    """``{'order': '<'|'>', 'ifds': {name: ('ok', [Entry]) | ('error', code, message)}}``; raises Damaged only for an unreadable header or IFD0."""
    order, first = header(tiff)
    budget, visited, ifds = [0], set(), {}

    def load(name, offset):
        if offset in visited:
            ifds[name] = ('error', 'INVALID_EXIF_STRUCTURE', name + ' repeats an earlier IFD (cycle or shared offset)')
            return None
        visited.add(offset)
        try:
            entries, following = read_ifd(tiff, offset, order, budget)
        except Damaged as error:
            ifds[name] = ('error', error.code, error.message)
            return None
        ifds[name] = ('ok', entries)
        return entries, following

    primary = load('IFD0', first)
    if primary is None:
        _, code, message = ifds['IFD0']
        raise Damaged(code, message)
    entries, following = primary
    for tag, name in POINTERS.items():
        found = [e for e in entries if e.tag == tag]
        if not found:
            continue
        if len(found) > 1 or found[0].kind != 4 or found[0].count != 1 or found[0].raw is None:
            ifds[name] = ('error', 'INVALID_EXIF_STRUCTURE', name + ' pointer is repeated or is not one LONG')
            continue
        load(name, struct.unpack(order + 'I', found[0].raw)[0])
    if following:
        chained = load('IFD1', following)
        if chained is not None and chained[1]:
            ifds['IFD1'] = ('error', 'INVALID_EXIF_STRUCTURE', 'the IFD chain is longer than IFD0 and IFD1')
    return {'order': order, 'ifds': ifds}
