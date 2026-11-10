#!/usr/bin/env python3
"""Independent, standard-library fixture measurements for Tesseract qualification.

The text pages under examples/schemaxis/fixtures/tesseract were drawn by tools/author_tesseract_fixtures.py; their literal
words are known from authoring. Here the ink of each line and word is measured straight from the PNG pixels, without any
recogniser output, so OCR word boxes can be bounded independently. Blank, RGBA, interlaced and truncated PNGs for refusal
controls are built synthetically and in memory.
"""
import struct
import zlib

from schemaxis import png as shared

LINE_GAP = 12      # blank pixel rows that separate two text lines
WORD_GAP = 20      # blank pixel columns that separate two words
DARK = 128


def chunk(kind, body):
    return struct.pack('>I', len(body)) + kind + body + struct.pack('>I', zlib.crc32(kind + body))


def build_png(width, height, pixels, colour=2, interlace=0):
    channels = 3 if colour == 2 else 4
    stride = width * channels
    raw = b''.join(b'\x00' + pixels[y * stride:(y + 1) * stride] for y in range(height))
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, colour, 0, 0, interlace))
            + chunk(b'IDAT', zlib.compress(raw, 9)) + chunk(b'IEND', b''))


def blank(width=200, height=80):
    return build_png(width, height, bytes([255]) * (3 * width * height))


def rgba_from(data):
    """The same picture as an RGBA PNG (an unsupported input for the OCR route)."""
    width, height, rgba = shared.decode(data)
    return build_png(width, height, rgba, colour=6)


def interlaced_flag(data):
    """The same picture with the IHDR interlace byte set; only the header is judged by the route's refusal."""
    head = bytearray(data)
    head[28] = 1
    head[29:33] = struct.pack('>I', zlib.crc32(bytes(head[12:29])))
    return bytes(head)


def measure(data):
    """Independent ink geometry: width, height and per line [(top, bottom, [(left, right) per word])], inclusive pixel indices."""
    width, height, rgba = shared.decode(data)
    dark = [[(rgba[4 * (y * width + x)] + rgba[4 * (y * width + x) + 1] + rgba[4 * (y * width + x) + 2]) // 3 < DARK for x in range(width)] for y in range(height)]
    rows = [y for y in range(height) if any(dark[y])]
    bands, start, previous = [], None, None
    for y in rows:
        if start is None:
            start = previous = y
        elif y - previous > LINE_GAP:
            bands.append((start, previous))
            start = previous = y
        else:
            previous = y
    if start is not None:
        bands.append((start, previous))
    lines = []
    for top, bottom in bands:
        columns = [x for x in range(width) if any(dark[y][x] for y in range(top, bottom + 1))]
        words, first, last = [], None, None
        for x in columns:
            if first is None:
                first = last = x
            elif x - last > WORD_GAP:
                words.append((first, last))
                first = last = x
            else:
                last = x
        if first is not None:
            words.append((first, last))
        lines.append((top, bottom, words))
    return {'width': width, 'height': height, 'lines': lines}


def scanned_pdf(pages):
    """A two-or-more page PDF whose pages are only an embedded RGB raster (a scan): no text objects, so text extraction finds nothing.

    Each page is the picture at one point per pixel, so a 72 dpi render is one-to-one. ``pages`` are opaque RGB PNG bytes."""
    objects, kids, body = [], [], []
    count = len(pages)
    def add(content):
        objects.append(content);return len(objects)
    add(b'')  # catalog placeholder (1)
    add(b'')  # pages placeholder (2)
    for png_bytes in pages:
        width, height, rgba = shared.decode(png_bytes)
        rgb = bytearray(3 * width * height)
        rgb[0::3], rgb[1::3], rgb[2::3] = rgba[0::4], rgba[1::4], rgba[2::4]
        data = zlib.compress(bytes(rgb), 9)
        image = add(b'<< /Type /XObject /Subtype /Image /Width %d /Height %d /ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /FlateDecode /Length %d >>\nstream\n' % (width, height, len(data)) + data + b'\nendstream')
        content = b'q %d 0 0 %d 0 0 cm /Im0 Do Q' % (width, height)
        stream = add(b'<< /Length %d >>\nstream\n' % len(content) + content + b'\nendstream')
        kids.append(add(b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 %d %d] /Resources << /XObject << /Im0 %d 0 R >> >> /Contents %d 0 R >>' % (width, height, image, stream)))
    objects[0] = b'<< /Type /Catalog /Pages 2 0 R >>'
    objects[1] = b'<< /Type /Pages /Kids [%s] /Count %d >>' % (b' '.join(b'%d 0 R' % k for k in kids), count)
    out = bytearray(b'%PDF-1.4\n%\xe2\xe3\xcf\xd3\n');offsets = []
    for number, content in enumerate(objects, 1):
        offsets.append(len(out));out += b'%d 0 obj\n' % number + content + b'\nendobj\n'
    start = len(out)
    out += b'xref\n0 %d\n0000000000 65535 f \n' % (len(objects) + 1) + b''.join(b'%010d 00000 n \n' % o for o in offsets)
    out += b'trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n' % (len(objects) + 1, start)
    return bytes(out)
