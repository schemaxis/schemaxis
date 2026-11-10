"""Hand-built container fixtures for the E5 tests (standard library only; every file is assembled from literal bytes and opaque payloads).

Nothing here decodes a codec or claims a pixel: strips, tiles, bitstreams and HEIF item payloads are short opaque byte strings, so the protected
bytes of every fixture are authored by the test and its expectations stay independent of the locators and of ExifTool. TIFF files are
assembled with labelled parts whose offsets are resolved in two passes (sizes never depend on offsets); PNG, RIFF and ISO-BMFF files are
concatenated boxes and chunks.
"""
from collections import defaultdict
import struct
import zlib

STRIP = bytes([10, 20, 30, 40, 50, 60])
BLOB = b'OPAQUE-BLOB-A-16'
XMP_TEXT = ('<x:xmpmeta xmlns:x="adobe:ns:meta/"><rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">'
            '<rdf:Description rdf:about="" xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title><rdf:Alt>'
            '<rdf:li xml:lang="x-default">Quarry gate</rdf:li></rdf:Alt></dc:title></rdf:Description></rdf:RDF></x:xmpmeta>').encode()
ASCII, SHORT, LONG, RATIONAL, UNDEFINED, SRATIONAL, IFDTYPE = 2, 3, 4, 5, 7, 10, 13


# TIFF ---------------------------------------------------------------------------------------------------------------------------------

def short(o, value):
    return struct.pack(o + 'H', value) + b'\0\0'


def long(o, value):
    return struct.pack(o + 'I', value)


def row(o, tag, kind, count, field):
    assert len(field) == 4
    return struct.pack(o + 'HHI', tag, kind, count) + field


def ifd(o, rows, following=0):
    return struct.pack(o + 'H', len(rows)) + b''.join(rows) + struct.pack(o + 'I', following)


def assemble(o, parts):
    """``parts`` is ``[(label, make)]``; ``make(offsets)`` returns bytes. The header takes bytes 0..7 and the first part is IFD0."""
    offsets = defaultdict(int)
    out = b''
    for _ in range(2):
        position, pieces = 8, []
        for label, make in parts:
            offsets[label] = position
            piece = make(offsets)
            position += len(piece)
            pieces.append(piece)
        out = pieces
    return (b'II*\0' if o == '<' else b'MM\0*') + struct.pack(o + 'I', 8) + b''.join(out)


def base_rows(o, off, strip='strip', size=len(STRIP)):
    return [row(o, 0x100, SHORT, 1, short(o, 3)), row(o, 0x101, SHORT, 1, short(o, 2)), row(o, 0x102, SHORT, 1, short(o, 8)), row(o, 0x103, SHORT, 1, short(o, 1)),
            row(o, 0x106, SHORT, 1, short(o, 1)), row(o, 0x111, LONG, 1, long(o, off[strip])), row(o, 0x115, SHORT, 1, short(o, 1)), row(o, 0x116, SHORT, 1, short(o, 2)),
            row(o, 0x117, LONG, 1, long(o, size))]


def text_row(o, tag, text, label, off):
    data = text.encode() + b'\0'
    return row(o, tag, ASCII, len(data), long(o, off[label]))


def text_block(text):
    data = text.encode() + b'\0'
    return data + (b'\0' if len(data) % 2 else b'')


def plain_tiff(o='<', title='Quarry gate', creator='A. Mason'):
    """T-1/T-2: one strip, ImageDescription and Artist as out-of-line values."""
    def table(off):
        rows = base_rows(o, off) + [text_row(o, 0x010E, title, 'title', off), text_row(o, 0x013B, creator, 'creator', off)]
        return ifd(o, sorted(rows, key=lambda r: struct.unpack(o + 'H', r[:2])[0]))
    return assemble(o, [('ifd0', table), ('title', lambda off: text_block(title)), ('creator', lambda off: text_block(creator)), ('strip', lambda off: STRIP)])


def tiled_tiff(o='<'):
    """T-3: 32x32 image of four 16x16 tiles of 8 opaque bytes each (compression code 5 so the native writer does not expect full-size raw tiles)."""
    tiles = [bytes([i] * 8) for i in (1, 2, 3, 4)]
    def table(off):
        rows = [row(o, 0x100, SHORT, 1, short(o, 32)), row(o, 0x101, SHORT, 1, short(o, 32)), row(o, 0x102, SHORT, 1, short(o, 8)), row(o, 0x103, SHORT, 1, short(o, 5)),
                row(o, 0x106, SHORT, 1, short(o, 1)), row(o, 0x115, SHORT, 1, short(o, 1)), row(o, 0x142, SHORT, 1, short(o, 16)), row(o, 0x143, SHORT, 1, short(o, 16)),
                row(o, 0x144, LONG, 4, long(o, off['offs'])), row(o, 0x145, LONG, 4, long(o, off['counts']))]
        return ifd(o, rows)
    parts = [('ifd0', table), ('offs', lambda off: b''.join(long(o, off['t%d' % i]) for i in range(4))), ('counts', lambda off: long(o, 8) * 4)]
    parts += [('t%d' % i, lambda off, i=i: tiles[i]) for i in range(4)]
    return assemble(o, parts), tiles


def lzw_tiff(o='<'):
    """T-4: three strips of 4, 5 and 6 opaque bytes with compression code 5; no decompression is implied."""
    strips = [b'\x01' * 4, b'\x02' * 5, b'\x03' * 6]
    def table(off):
        rows = [row(o, 0x100, SHORT, 1, short(o, 3)), row(o, 0x101, SHORT, 1, short(o, 3)), row(o, 0x102, SHORT, 1, short(o, 8)), row(o, 0x103, SHORT, 1, short(o, 5)),
                row(o, 0x106, SHORT, 1, short(o, 1)), row(o, 0x111, LONG, 3, long(o, off['offs'])), row(o, 0x115, SHORT, 1, short(o, 1)), row(o, 0x116, SHORT, 1, short(o, 1)),
                row(o, 0x117, LONG, 3, long(o, off['counts']))]
        return ifd(o, rows)
    parts = [('ifd0', table), ('offs', lambda off: b''.join(long(o, off['s%d' % i]) for i in range(3))), ('counts', lambda off: b''.join(long(o, len(s)) for s in strips))]
    parts += [('s%d' % i, lambda off, i=i: strips[i]) for i in range(3)]
    return assemble(o, parts), strips


def two_page_tiff(o='<'):
    """T-5: IFD0 chained to a second page with its own strip."""
    second = bytes([70, 80, 90])
    def first(off):
        return ifd(o, base_rows(o, off), off['page2'])
    def page2(off):
        rows = [row(o, 0x100, SHORT, 1, short(o, 3)), row(o, 0x101, SHORT, 1, short(o, 1)), row(o, 0x102, SHORT, 1, short(o, 8)), row(o, 0x103, SHORT, 1, short(o, 1)),
                row(o, 0x106, SHORT, 1, short(o, 1)), row(o, 0x111, LONG, 1, long(o, off['strip2'])), row(o, 0x115, SHORT, 1, short(o, 1)), row(o, 0x116, SHORT, 1, short(o, 1)),
                row(o, 0x117, LONG, 1, long(o, 3))]
        return ifd(o, rows)
    return assemble(o, [('ifd0', first), ('page2', page2), ('strip', lambda off: STRIP), ('strip2', lambda off: second)])


def overlapping_strips_tiff(o='<'):
    """T-6: two strips whose extents overlap by three bytes."""
    def table(off):
        rows = [row(o, 0x100, SHORT, 1, short(o, 3)), row(o, 0x101, SHORT, 1, short(o, 2)), row(o, 0x102, SHORT, 1, short(o, 8)), row(o, 0x103, SHORT, 1, short(o, 1)),
                row(o, 0x106, SHORT, 1, short(o, 1)), row(o, 0x111, LONG, 2, long(o, off['offs'])), row(o, 0x115, SHORT, 1, short(o, 1)), row(o, 0x116, SHORT, 1, short(o, 1)),
                row(o, 0x117, LONG, 2, long(o, off['counts']))]
        return ifd(o, rows)
    return assemble(o, [('ifd0', table), ('offs', lambda off: long(o, off['strip']) + long(o, off['strip'] + 3)), ('counts', lambda off: long(o, 6) + long(o, 6)),
                        ('strip', lambda off: STRIP + b'\x07\x08\x09')])


def beyond_eof_tiff(o='<'):
    """T-7: the strip byte count runs past the end of the file."""
    def table(off):
        rows = base_rows(o, off, size=4096)
        return ifd(o, rows)
    return assemble(o, [('ifd0', table), ('strip', lambda off: STRIP)])


def bigtiff():
    return b'II+\0' + struct.pack('<HHQ', 8, 0, 16) + b'\0' * 24


def subifd_cycle_tiff(o='<'):
    """T-9: IFD0's SubIFDs entry points back at IFD0."""
    def table(off):
        return ifd(o, base_rows(o, off) + [row(o, 0x014A, LONG, 1, long(o, 8))])
    return assemble(o, [('ifd0', table), ('strip', lambda off: STRIP)])


def interop_tiff(o='<', value=b'R98'):
    """T-10: ExifIFD carrying an InteropIFD with InteroperabilityIndex ``R98``."""
    def table(off):
        rows = base_rows(o, off) + [row(o, 0x8769, LONG, 1, long(o, off['exif']))]
        return ifd(o, sorted(rows, key=lambda r: struct.unpack(o + 'H', r[:2])[0]))
    def exif(off):
        return ifd(o, [row(o, 0xA005, LONG, 1, long(o, off['interop']))])
    def interop(off):
        return ifd(o, [row(o, 0x0001, ASCII, 4, value.ljust(3, b'\0')[:3] + b'\0')])
    return assemble(o, [('ifd0', table), ('exif', exif), ('interop', interop), ('strip', lambda off: STRIP)])


def gps_tiff(o='<'):
    """T-R1: a GPS IFD with a latitude reference and an ExifIFD with an ExifVersion value."""
    def table(off):
        rows = base_rows(o, off) + [row(o, 0x8769, LONG, 1, long(o, off['exif'])), row(o, 0x8825, LONG, 1, long(o, off['gps']))]
        return ifd(o, sorted(rows, key=lambda r: struct.unpack(o + 'H', r[:2])[0]))
    return assemble(o, [('ifd0', table), ('exif', lambda off: ifd(o, [row(o, 0x9000, UNDEFINED, 4, b'0232')])),
                        ('gps', lambda off: ifd(o, [row(o, 0x0001, ASCII, 2, b'N\0\0\0')])), ('strip', lambda off: STRIP)])


def jpeg_thumbnail_tiff(o='<'):
    """T-12: IFD1 holds a JPEG-interchange thumbnail of 6 opaque bytes."""
    thumb = b'\xff\xd8thum'
    def first(off):
        return ifd(o, base_rows(o, off), off['ifd1'])
    def second(off):
        return ifd(o, [row(o, 0x0201, LONG, 1, long(o, off['thumb'])), row(o, 0x0202, LONG, 1, long(o, len(thumb)))])
    return assemble(o, [('ifd0', first), ('ifd1', second), ('strip', lambda off: STRIP), ('thumb', lambda off: thumb)]), thumb


def dng(o='<', private=b'VendorPrivate-0123', *, make_private=True, artist=None):
    """D-1: a DNG whose IFD0 is a preview strip, with colour matrix, private data and a CFA raw image in a SubIFD."""
    raw = bytes(range(32, 48))
    matrix = b''.join(struct.pack(o + 'ii', n, 10000) for n in (6000, -1500, 300, -4200, 11200, 800, -900, 2200, 5100))
    def table(off):
        rows = base_rows(o, off) + [row(o, 0x014A, LONG, 1, long(o, off['sub'])), row(o, DNGVERSION, 1, 4, bytes([1, 4, 0, 0])), row(o, 0xC613, 1, 4, bytes([1, 1, 0, 0])),
                                    row(o, 0xC621, SRATIONAL, 9, long(o, off['matrix']))]
        if make_private:
            rows.append(row(o, 0xC634, UNDEFINED, len(private), long(o, off['private'])))
        if artist is not None:
            rows.append(text_row(o, 0x013B, artist, 'artist', off))
        return ifd(o, sorted(rows, key=lambda r: struct.unpack(o + 'H', r[:2])[0]))
    def sub(off):
        rows = [row(o, 0x00FE, LONG, 1, long(o, 0)), row(o, 0x100, SHORT, 1, short(o, 4)), row(o, 0x101, SHORT, 1, short(o, 4)), row(o, 0x102, SHORT, 1, short(o, 8)),
                row(o, 0x103, SHORT, 1, short(o, 1)), row(o, 0x106, SHORT, 1, short(o, 32803)), row(o, 0x111, LONG, 1, long(o, off['raw'])), row(o, 0x115, SHORT, 1, short(o, 1)),
                row(o, 0x116, SHORT, 1, short(o, 4)), row(o, 0x117, LONG, 1, long(o, 16)), row(o, 0xC617, SHORT, 2, short(o, 2)[:2] + short(o, 2)[:2])]
        return ifd(o, rows)
    parts = [('ifd0', table), ('sub', sub), ('matrix', lambda off: matrix), ('private', lambda off: private + (b'\0' if len(private) % 2 else b'')),
             ('strip', lambda off: STRIP), ('raw', lambda off: raw)] + ([('artist', lambda off: text_block(artist))] if artist is not None else [])
    return assemble(o, parts), raw, matrix


DNGVERSION = 0xC612


def private_tag_tiff(variant):
    """T-11 fixtures a1, a2, u8, s1, i1 (private tag pointing at an unreferenced 16-byte block), 192 bytes each, little-endian."""
    entries = [(0x100, SHORT, 1, 3), (0x101, SHORT, 1, 2), (0x102, SHORT, 1, 8), (0x103, SHORT, 1, 1), (0x106, SHORT, 1, 1), (0x111, LONG, 1, None), (0x115, SHORT, 1, 1),
               (0x116, SHORT, 1, 2), (0x117, LONG, 1, 6)]
    private = {'a1': (0xC7F0, LONG, 1), 'a2': (0xC7F0, LONG, 2), 'u8': (0xC7F1, UNDEFINED, 8), 'i1': (0xC7F2, IFDTYPE, 1), 's1': (0xC7F3, 9, 1)}[variant]
    entries.append(private + (None,))
    o = '<'
    count = len(entries)
    external = 8 + 2 + 12 * count + 4
    strip, blob, private_ifd = external + 16, external + 16 + 6 + 2, external + 16 + 6 + 2 + 16
    rows, values = [], b''
    for tag, kind, number, value in entries:
        if tag == 0x111:
            field = long(o, strip)
        elif tag == private[0]:
            if variant in ('a1', 's1'):
                field = long(o, blob)
            elif variant == 'i1':
                field = long(o, private_ifd)
            else:
                values, field = struct.pack(o + 'II', blob, 16), long(o, external)
        else:
            field = short(o, value) if kind == SHORT else long(o, value)
        rows.append(row(o, tag, kind, number, field))
    out = b'II*\0' + struct.pack('<I', 8) + ifd(o, rows) + values.ljust(16, b'\0') + STRIP + b'\0\0' + BLOB
    out += struct.pack('<H', 1) + struct.pack('<HHI', 1, LONG, 1) + struct.pack('<I', 0x11223344) + struct.pack('<I', 0)
    assert len(out) == 192 and out.index(BLOB) == blob
    return out


def _flat_tiff(rows_tail, tail):
    """Ten-entry IFD0 at offset 8 followed directly by ``tail`` (no out-of-line values)."""
    o = '<'
    strip = 8 + 2 + 12 * 10 + 4
    rows = [row(o, 0x100, SHORT, 1, short(o, 3)), row(o, 0x101, SHORT, 1, short(o, 2)), row(o, 0x102, SHORT, 1, short(o, 8)), row(o, 0x103, SHORT, 1, short(o, 1)),
            row(o, 0x106, SHORT, 1, short(o, 1)), row(o, 0x111, LONG, 1, long(o, strip)), row(o, 0x115, SHORT, 1, short(o, 1)), row(o, 0x116, SHORT, 1, short(o, 2)),
            row(o, 0x117, LONG, 1, long(o, 6))] + rows_tail(strip)
    return b'II*\0' + struct.pack('<I', 8) + ifd(o, rows) + tail


def duplicate_pointer_tiff():
    """T-11f: private LONG equal to the strip start, no gaps anywhere."""
    return _flat_tiff(lambda strip: [row('<', 0xC7F0, LONG, 1, long('<', strip))], STRIP)


def plain_private_pair_tiff():
    """T-11g: private LONG[2] {3, 7} stored out of line directly after IFD0, then the strip; no gaps and no region start among the words."""
    o = '<'
    external = 8 + 2 + 12 * 10 + 4
    rows = [row(o, 0x100, SHORT, 1, short(o, 3)), row(o, 0x101, SHORT, 1, short(o, 2)), row(o, 0x102, SHORT, 1, short(o, 8)), row(o, 0x103, SHORT, 1, short(o, 1)),
            row(o, 0x106, SHORT, 1, short(o, 1)), row(o, 0x111, LONG, 1, long(o, external + 8)), row(o, 0x115, SHORT, 1, short(o, 1)), row(o, 0x116, SHORT, 1, short(o, 2)),
            row(o, 0x117, LONG, 1, long(o, 6)), row(o, 0xC7F0, LONG, 2, long(o, external))]
    return b'II*\0' + struct.pack('<I', 8) + ifd(o, rows) + struct.pack('<II', 3, 7) + STRIP


def gap_tiff(unknown):
    """T-11h/T-11h0: a 32-byte non-padding gap after the strip; ``unknown`` selects an unrecognised ASCII tag (0xC7F4) or the known Artist tag."""
    tag = 0xC7F4 if unknown else 0x013B
    return _flat_tiff(lambda strip: [struct.pack('<HHI', tag, ASCII, 4) + b'abc\0'], STRIP + b'G' * 32)


def offset_tag_tiff():
    """T-11i: FreeOffsets (0x0120) present."""
    return _flat_tiff(lambda strip: [row('<', 0x0120, LONG, 1, long('<', 0))], STRIP)


def three_strip_tiff_with_xmp_iptc(o='<'):
    """TIFF carrying an XMP packet (0x02BC) and bare IPTC-IIM (0x83BB) with the title 2:5 'Gate' and a Photoshop resource block (0x8649) with none."""
    iim = b'\x1c\x02\x05\x00\x04Gate'
    def table(off):
        rows = base_rows(o, off) + [row(o, 0x02BC, 1, len(XMP_TEXT), long(o, off['xmp'])), row(o, 0x83BB, 1, len(iim), long(o, off['iim']))]
        return ifd(o, sorted(rows, key=lambda r: struct.unpack(o + 'H', r[:2])[0]))
    return assemble(o, [('ifd0', table), ('xmp', lambda off: XMP_TEXT + (b'\0' if len(XMP_TEXT) % 2 else b'')), ('iim', lambda off: iim + (b'\0' if len(iim) % 2 else b'')),
                        ('strip', lambda off: STRIP)]), iim


def photoshop_block(ident, data, name=b''):
    """One Photoshop image resource (8BIM, id, Pascal name padded to even, size, data padded to even)."""
    pascal = bytes([len(name)]) + name
    pascal += b'\0' * (len(pascal) % 2)
    return b'8BIM' + struct.pack('>H', ident) + pascal + struct.pack('>I', len(data)) + data + (b'\0' if len(data) % 2 else b'')


def photoshop_tiff(o='<', *, tail=b'', digest=False, iim=b'\x1c\x02\x05\x00\x04Gate'):
    """Mailbox 7: a TIFF whose IPTC lives in a Photoshop image-resource block (tag 0x8649): an IPTC-NAA resource (0x0404), one opaque non-IPTC plugin resource (0x0FA1 'OPAQUE-PLUGIN'), an
    optional IPTC digest (0x0425, the MD5 of the IIM) and an optional opaque ``tail`` after the last resource (shorter than the 12 bytes the shared reader needs for a resource, so
    ``iptc.resources`` ignores it without an error)."""
    import hashlib
    blocks = photoshop_block(0x0404, iim) + photoshop_block(0x0FA1, b'OPAQUE-PLUGIN') + (photoshop_block(0x0425, hashlib.md5(iim).digest()) if digest else b'') + tail
    def table(off):
        rows = base_rows(o, off) + [row(o, 0x8649, UNDEFINED, len(blocks), long(o, off['psir']))]
        return ifd(o, sorted(rows, key=lambda r: struct.unpack(o + 'H', r[:2])[0]))
    return assemble(o, [('ifd0', table), ('psir', lambda off: blocks + (b'\0' if len(blocks) % 2 else b'')), ('strip', lambda off: STRIP)]), blocks


# PNG ----------------------------------------------------------------------------------------------------------------------------------

PNG_SIGNATURE = b'\x89PNG\r\n\x1a\n'


def chunk(kind, data=b'', *, crc=None):
    checksum = zlib.crc32(kind + data) & 0xFFFFFFFF if crc is None else crc
    return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', checksum)


def ihdr(width=2, height=2):
    return chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0))


def png(*chunks, signature=PNG_SIGNATURE):
    return signature + b''.join(chunks)


def exif_stream(o='<', artist='A. Mason'):
    """A TIFF stream with one IFD0 Artist entry (the payload of eXIf, WebP EXIF and HEIF Exif items)."""
    def table(off):
        return ifd(o, [text_row(o, 0x013B, artist, 'artist', off)])
    return assemble(o, [('ifd0', table), ('artist', lambda off: text_block(artist))])


def xmp_itxt(text=XMP_TEXT, *, compressed=False, keyword=b'XML:com.adobe.xmp'):
    body = zlib.compress(text) if compressed else text
    return chunk(b'iTXt', keyword + b'\0' + bytes([1 if compressed else 0, 0]) + b'\0\0' + body)


def text_chunk(keyword, text, kind=b'tEXt'):
    if kind == b'tEXt':
        return chunk(b'tEXt', keyword + b'\0' + text)
    return chunk(b'zTXt', keyword + b'\0\0' + zlib.compress(text))


IDAT = chunk(b'IDAT', b'\x08\xd7opaque')
IEND = chunk(b'IEND')
GAMA = chunk(b'gAMA', struct.pack('>I', 45455))


def basic_png(*, metadata=True):
    chunks = [ihdr(), GAMA, text_chunk(b'Comment', b'plain text')]
    if metadata:
        chunks += [chunk(b'eXIf', exif_stream()), xmp_itxt()]
    return png(*chunks, IDAT, IEND)


# WebP ---------------------------------------------------------------------------------------------------------------------------------

def ck(fourcc, body):
    return fourcc + struct.pack('<I', len(body)) + body + (b'\0' if len(body) & 1 else b'')


def riff(*chunks):
    body = b'WEBP' + b''.join(chunks)
    return b'RIFF' + struct.pack('<I', len(body)) + body


def vp8(width=3, height=2, odd=True):
    """An opaque lossy payload with a valid key-frame header; 17 bytes (odd, so one pad byte) unless ``odd`` is false (16 is the shortest the native writer reads)."""
    return b'\x10\x02\x00' + b'\x9d\x01\x2a' + struct.pack('<HH', width, height) + b'\xaa' * (7 if odd else 6)


def vp8l(width=3, height=2, alpha=False):
    bits = (width - 1) | ((height - 1) << 14) | (int(alpha) << 28)
    return b'\x2f' + struct.pack('<I', bits) + b'\xbb\xcc\xdd'


def vp8x(flags, width=3, height=2):
    return ck(b'VP8X', bytes([flags, 0, 0, 0]) + (width - 1).to_bytes(3, 'little') + (height - 1).to_bytes(3, 'little'))


ICC = bytes(36) + b'acsp' + bytes(92)
ALPH = b'\x00' + bytes([0x80] * 6)
UNKNOWN = ck(b'zzzz', b'opaque!')


def anmf():
    return ck(b'ANMF', b'\0\0\0\0\0\0' + (2).to_bytes(3, 'little') + (1).to_bytes(3, 'little') + (100).to_bytes(3, 'little') + b'\0' + ck(b'VP8 ', vp8()))


def webp_exif():
    return ck(b'EXIF', exif_stream())


def webp_xmp():
    return ck(b'XMP ', XMP_TEXT)


# HEIF ---------------------------------------------------------------------------------------------------------------------------------

def box(kind, body):
    return struct.pack('>I4s', 8 + len(body), kind) + body


def full(kind, body, version=0, flags=0):
    return box(kind, bytes([version]) + flags.to_bytes(3, 'big') + body)


def infe(ident, kind, *, content_type=None, hidden=False, protection=0, name=b''):
    body = struct.pack('>HH', ident, protection) + kind + name + b'\0'
    if content_type is not None:
        body += content_type + b'\0'
    return full(b'infe', body, 2, 1 if hidden else 0)


def exif_item(o='<', artist='A. Mason'):
    return struct.pack('>I', 6) + b'Exif\0\0' + exif_stream(o, artist)


def heic(items, *, primary=1, refs=(), props=((b'ispe', 64, 48),), associations=None, brand=b'heic', compat=(b'mif1',), base_size=0, version=1, idat=b'', extra_meta=b'',
         extra_top=b'', top_after=b'', iref_version=0, layout=None):
    """A minimal HEIC. ``items`` are dicts: id, type, payload, optional content_type, hidden, protection, method (0 file, 1 idat, 2 unsupported), dri, implied, base.

    ``layout`` lists item ids in the order their payloads are stored (default: item order). A ``share_with`` item id makes an item point at another item's bytes without storing any of its own. ``refs`` is ``[(type, from, [to...])]``. Properties are ``(b'ispe', width, height)`` or ``(kind, raw_body)``. Payloads of method 0 are laid out in ``mdat`` in
    item order and offsets are resolved in two passes (iloc field sizes are fixed, so sizes never depend on offsets).
    """
    ftyp = box(b'ftyp', brand + b'\0\0\0\0' + b''.join(compat))
    by_id = {}
    for item in items:
        by_id.setdefault(item['id'], item)
    placement = [by_id[i] for i in layout] if layout else [i for i in items]
    stored = [i for i in placement if i.get('method', 0) == 0 and i.get('share_with') is None]

    def meta(mdat_start):
        starts, position = {}, mdat_start
        for item in stored:
            starts[item['id']] = position
            position += len(item.get('payload', b''))
        rows = b''
        for item in items:
            payload = item.get('payload', b'')
            method = item.get('method', 0)
            base = item.get('base', 0)
            if item.get('share_with') is not None:
                extent_offset = starts[item['share_with']] - base
            elif method == 0:
                extent_offset = starts[item['id']] - base
            elif method == 1:
                extent_offset = item.get('idat_offset', 0) - base
            else:
                extent_offset = item.get('offset', 0)
            if item.get('share_with') is not None:
                payload = by_id[item['share_with']].get('payload', b'')
            length = 0 if item.get('implied') else (len(payload) if method != 2 else item.get('length', 0))
            row_bytes = struct.pack('>H', item['id']) + (struct.pack('>H', method) if version else b'') + struct.pack('>H', item.get('dri', 0))
            row_bytes += (struct.pack('>I', base) if base_size else b'') + struct.pack('>H', 1) + struct.pack('>II', extent_offset, length)
            rows += row_bytes
        iloc = full(b'iloc', bytes([0x44, (base_size << 4)]) + struct.pack('>H', len(items)) + rows, version)
        iinf = full(b'iinf', struct.pack('>H', len(items)) + b''.join(infe(i['id'], i['type'], content_type=i.get('content_type'), hidden=i.get('hidden', False),
                                                                             protection=i.get('protection', 0)) for i in items))
        ipco = box(b'ipco', b''.join(full(b'ispe', struct.pack('>II', p[1], p[2])) if p[0] == b'ispe' else box(p[0], p[1]) for p in props))
        wanted = associations if associations is not None else {primary: list(range(1, len(props) + 1))}
        ipma = full(b'ipma', struct.pack('>I', len(wanted)) + b''.join(struct.pack('>HB', i, len(a)) + bytes(a) for i, a in wanted.items()))
        iref = b''
        if refs:
            wide = '>I' if iref_version else '>H'
            iref = full(b'iref', b''.join(box(t, struct.pack(wide, f) + struct.pack('>H', len(to)) + b''.join(struct.pack(wide, x) for x in to)) for t, f, to in refs), iref_version)
        idat_box = box(b'idat', idat) if idat else b''
        hdlr = full(b'hdlr', b'\0\0\0\0pict' + bytes(12) + b'\0')
        pitm = full(b'pitm', struct.pack('>H', primary))
        return full(b'meta', hdlr + pitm + iinf + iloc + box(b'iprp', ipco + ipma) + iref + idat_box + extra_meta)
    first = meta(1 << 20)
    mdat_start = len(ftyp) + len(first) + len(extra_top) + 8
    final = meta(mdat_start)
    assert len(final) == len(first)
    payload = b''.join(i.get('payload', b'') for i in stored)
    return ftyp + final + extra_top + box(b'mdat', payload) + top_after


def heic_basic(*, with_metadata=False):
    items = [{'id': 1, 'type': b'hvc1', 'payload': b'OPAQUE-HVC1-IMAGE-24BYTES'[:24]}]
    refs = []
    if with_metadata:
        items += [{'id': 2, 'type': b'Exif', 'payload': exif_item()}, {'id': 3, 'type': b'mime', 'content_type': b'application/rdf+xml', 'payload': XMP_TEXT}]
        refs = [(b'cdsc', 2, [1]), (b'cdsc', 3, [1])]
    return heic(items, refs=refs)
