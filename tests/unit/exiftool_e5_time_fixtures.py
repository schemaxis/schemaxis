"""Hand-built TIFF, DNG, PNG, WebP and HEIC fixtures that carry capture times and positions (standard library only).

One Exif stream (the same literal entries as the E3 JPEG fixtures) is placed in each container's own Exif carrier, with optional XMP and IPTC, so the E5
time, location and transfer tests state every fixture and every expected value as a literal. No pixel is decoded; strips, bitstreams and item payloads are opaque.
"""
from pathlib import Path
import struct
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools'))
sys.path.insert(0, str(ROOT / 'tests/unit'))

import author_exiftool_fixtures as a  # noqa: E402
import exiftool_e3_fixtures as e3  # noqa: E402
import exiftool_e5_fixtures as f  # noqa: E402

TOKYO = e3.TOKYO
ORDER = 'II'


def stream(*, make='A', model='M', exif_version=b'0300', dto='2026:03:01 12:00:00', create=None, modify=None, off='+01:00', off_create=None, off_modify=None, sub='12',
           gps=None, exif=True, ifd0_extra=(), exif_extra=(), serial=None, order=ORDER):
    """The Exif TIFF stream (without the ``Exif\\0\\0`` prefix) with the E3 JPEG fixture's time and GPS entries; ``exif`` false leaves no ExifIFD."""
    ifd0 = [a.ascii_entry(0x010F, make), a.ascii_entry(0x0110, model)]
    if modify:
        ifd0.append(a.ascii_entry(0x0132, modify))
    ifd0 += list(ifd0_extra)
    ex = []
    if exif:
        if exif_version is not None:
            ex.append(a.undefined_entry(0x9000, exif_version))
        for tag, value in ((0x9003, dto), (0x9004, create), (0x9010, off_modify), (0x9011, off), (0x9012, off_create), (0x9290, None), (0x9291, sub), (0x9292, None), (0xA431, serial)):
            if value:
                ex.append(a.ascii_entry(tag, value))
        ex += list(exif_extra)
    return a.tiff_payload(order, ifd0, ex, e3.gps_entries(gps) if gps is not None else [])[6:]


def tiff(*, xmp=None, iptc=None, strips=f.STRIP, dng=False, ifd0_extra=(), **kw):
    """A single-strip TIFF whose IFD0 also carries the Exif/GPS pointers of ``stream`` (and an XMP packet in tag 0x02BC, IIM in 0x83BB, when given)."""
    def build(strip_offset):
        extra = [a.long_entry(ORDER, 0x0111, strip_offset), a.long_entry(ORDER, 0x0117, len(strips)), (a.short_entry(ORDER, 0x0100, len(strips) // 2) if len(strips) // 2 <= 0xFFFF else a.long_entry(ORDER, 0x0100, len(strips) // 2)), a.short_entry(ORDER, 0x0101, 2), a.short_entry(ORDER, 0x0102, 8),
                 a.short_entry(ORDER, 0x0103, 1), a.short_entry(ORDER, 0x0106, 1), a.short_entry(ORDER, 0x0115, 1), a.short_entry(ORDER, 0x0116, 2)]
        if xmp is not None:
            extra.append(a.entry(0x02BC, 1, a.xmp_packet(xmp)))
        if iptc is not None:
            extra.append(a.entry(0x83BB, 7, _iim(iptc)))
        extra.extend(ifd0_extra)
        if dng:
            extra.append(a.entry(0xC612, 1, bytes([1, 4, 0, 0])))
            extra.append(a.entry(0xC614, 2, b'Synthetic DNG\0'))
        return stream(ifd0_extra=extra, **kw)
    first = build(0)
    final = build(len(first))
    assert len(final) == len(first)
    return final + strips


def _iim(datasets):
    return b''.join(a.iptc_dataset(r, n, v) for r, n, v in datasets)


def png(*, xmp=None, exif_block=True, **kw):
    chunks = [f.ihdr(), f.GAMA] + ([f.chunk(b'eXIf', stream(**kw))] if exif_block else [])
    if xmp is not None:
        chunks.append(f.xmp_itxt(a.xmp_packet(xmp)))
    return f.png(*chunks, f.IDAT, f.IEND)


def webp(*, xmp=None, exif_block=True, simple=False, **kw):
    flags = (0x08 if exif_block else 0) | (0x04 if xmp is not None else 0)
    chunks = ([] if simple else [f.vp8x(flags)]) + [f.ck(b'VP8 ', f.vp8())] + ([f.ck(b'EXIF', stream(**kw))] if exif_block else [])
    if xmp is not None:
        chunks.append(f.ck(b'XMP ', a.xmp_packet(xmp)))
    return f.riff(*chunks)


def heic(*, xmp=None, exif_block=True, **kw):
    """A HEIC whose Exif item (and, when given, XMP item) already exists, so the existing-item profile applies; ``exif_block`` false leaves no Exif item."""
    items = [{'id': 1, 'type': b'hvc1', 'payload': b'OPAQUE-HVC1-IMAGE-24BYTES'[:24]}]
    refs = []
    if exif_block:
        items.append({'id': 2, 'type': b'Exif', 'payload': struct.pack('>I', 0) + stream(**kw)})
        refs.append((b'cdsc', 2, [1]))
    if xmp is not None:
        items.append({'id': 3, 'type': b'mime', 'content_type': b'application/rdf+xml', 'payload': a.xmp_packet(xmp)})
        refs.append((b'cdsc', 3, [1]))
    return f.heic(items, refs=refs)


EXTENSIONS = {'tiff': '.tif', 'dng': '.dng', 'png': '.png', 'webp': '.webp', 'heif': '.heic'}


def container(kind, **kw):
    if kind == 'tiff':
        return tiff(**kw)
    if kind == 'dng':
        return tiff(dng=True, **kw)
    kw.pop('iptc', None)         # PNG, WebP and HEIF have no IPTC slot
    return {'png': png, 'webp': webp, 'heif': heic}[kind](**kw)


def full_time(kind, **kw):
    """EXIF 12:00:00 +01:00 .12 and the same wall time in XMP photoshop:DateCreated and (TIFF/DNG only) IPTC 2:55/2:60, as ``exiftool_e3_fixtures.full_time``."""
    base = dict(dto='2026:03:01 12:00:00', off='+01:00', sub='12', xmp=e3.xmp_properties(captured='2026-03-01T12:00:00.12+01:00'))
    if kind in ('tiff', 'dng'):
        base['iptc'] = [(2, 55, '20260301'), (2, 60, '120000+0100')]
    base.update(kw)
    return container(kind, **base)


# ---------------------------------------------------------------------------------------------------------------- minimise fixtures (AM-17)
def valid_icc():
    """A 152-byte ICC profile with one tag and a correct length, so ExifTool 13.55 reads it without a warning (opaque: no colour is computed)."""
    header = bytearray(128)
    header[8:12], header[12:16], header[16:20], header[20:24], header[36:40] = bytes([2, 0x10, 0, 0]), b'mntr', b'RGB ', b'XYZ ', b'acsp'
    body = bytes(header) + struct.pack('>I', 1) + b'cprt' + struct.pack('>II', 144, 8) + b'text\0\0\0\0'
    return struct.pack('>I', len(body)) + body[4:]


def exif_with(*, orientation=None, ycbcr=None, gps=True, color_space=None, **kw):
    """The Exif stream of the minimise fixtures: camera make/model, capture time, optional GPS, and the rendering values that the keep-set preserves."""
    extra = []
    if orientation is not None:
        extra.append(a.short_entry(ORDER, 0x0112, orientation))
    if ycbcr is not None:
        extra.append(a.short_entry(ORDER, 0x0213, ycbcr))
    return stream(ifd0_extra=extra, gps=TOKYO if gps else None, **kw)


def png_g6(**kw):
    """G-6/G-10: gAMA, iCCP, tIME, a tEXt Comment, an eXIf with Orientation (default 6), YCbCrPositioning 2 and a GPS IFD, and an XMP packet."""
    import zlib
    icc = f.chunk(b'iCCP', b'sRGB\0\0' + zlib.compress(valid_icc()))
    exif = exif_with(orientation=kw.pop('orientation', 6), ycbcr=kw.pop('ycbcr', 2), **kw)
    return f.png(f.ihdr(), f.GAMA, icc, f.chunk(b'tIME', bytes([7, 234, 3, 1, 12, 0, 0])), f.text_chunk(b'Comment', b'plain text'), f.chunk(b'eXIf', exif),
                 f.xmp_itxt(a.xmp_packet(e3.xmp_properties(captured='2026-03-01T12:00:00.12+01:00'))), f.IDAT, f.IEND)
