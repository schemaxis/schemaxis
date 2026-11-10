#!/usr/bin/env python3
"""Original synthetic field-photo JPEG fixtures for the ExifTool adaptor (standard library only).

Usage: author_exiftool_fixtures.py OUTPUT-DIRECTORY

Every file is generated here from literal specifications; no real photograph, camera file, GPS fix or third-party sample
is used. Each image is a tiny baseline 8-bit three-component JFIF JPEG (1x1 sampling) whose blocks carry only DC
coefficients: the pixels are a synthetic colour pattern, never a scene. The EXIF segment is assembled byte by byte so
qualification can derive its expected values from the literal specification below, not from ExifTool or from the
adaptor's reader. ``build`` is also the mutation source for qualification and tests (duplicate tags, bad types, cycles).
"""
import struct
import sys
from pathlib import Path

ASCII, SHORT, LONG = 2, 3, 4
IFD0_MAKE, IFD0_MODEL, IFD0_ORIENTATION, IFD0_EXIF, IFD0_GPS, IFD0_SOFTWARE = 0x010F, 0x0110, 0x0112, 0x8769, 0x8825, 0x0131
EXIF_ORIGINAL, EXIF_OFFSET = 0x9003, 0x9011

# Literal expectations (width, height, spec) used by qualification as the independent oracle.
FIXTURES = {
    'north-gate': dict(width=16, height=8, order='II', make='Northfield', model='NF-100', orientation=1,
                       original='2024:05:06 07:08:09', offset='+02:00', software='Synthetic fixture generator'),
    'river-bend': dict(width=8, height=16, order='MM', make='Riverside Optics', model='RB 7', orientation=6,
                       original='2023:12:31 23:59:58', offset='-05:30', gps=True),
    'quarry': dict(width=24, height=8, order='II', make='Q', model='=SUM(1+1)', orientation=3,
                   original='2024:02:29 00:00:00'),
    'unmarked': dict(width=8, height=8, order='MM'),
    'short-strings': dict(width=16, height=16, order='II', make='Abc', model='Dx', orientation=8,
                          original='2022:01:02 03:04:05', offset='+00:00'),
}


def pack(order, fmt, *values):
    return struct.pack(('<' if order == 'II' else '>') + fmt, *values)


def entry(tag, kind, value, count=None):
    """One IFD entry: ``value`` is the raw value bytes (ASCII text without its terminator is not added here)."""
    size = {1: 1, ASCII: 1, SHORT: 2, LONG: 4, 5: 8, 7: 1, 10: 8}[kind]
    return (tag, kind, value, len(value) // size if count is None else count)


def ascii_entry(tag, text):
    return entry(tag, ASCII, text.encode('ascii') + b'\0')


def ifd(order, entries, start, next_offset=0, order_entries=True):
    """Return (table, data): out-of-line values are placed directly after the table, four-byte aligned."""
    rows = sorted(entries, key=lambda e: e[0]) if order_entries else list(entries)
    table_length = 2 + 12 * len(rows) + 4
    data = b''
    table = pack(order, 'H', len(rows))
    for tag, kind, value, count in rows:
        if len(value) <= 4:
            table += pack(order, 'HHI', tag, kind, count)[:8] + value.ljust(4, b'\0')
        else:
            table += pack(order, 'HHII', tag, kind, count, start + table_length + len(data))
            data += value + (b'\0' if len(value) % 2 else b'')
    return table + pack(order, 'I', next_offset), data


def exif_segment(order='II', make=None, model=None, orientation=None, original=None, offset=None, software=None, gps=False,
                 extra0=(), extra_exif=(), ifd0_next=0, exif_pointer=None, exif_pointer_kind=LONG, gps_pointer_value=None):
    """Assemble an APP1 Exif payload (without marker/length); returns None when nothing is selected."""
    ifd0 = [e for e in (ascii_entry(IFD0_MAKE, make) if make is not None else None, ascii_entry(IFD0_MODEL, model) if model is not None else None,
                        entry(IFD0_ORIENTATION, SHORT, pack(order, 'H', orientation)) if orientation is not None else None,
                        ascii_entry(IFD0_SOFTWARE, software) if software is not None else None) if e is not None]
    ifd0 += list(extra0)
    exif = [e for e in (ascii_entry(EXIF_ORIGINAL, original) if original is not None else None,
                        ascii_entry(EXIF_OFFSET, offset) if offset is not None else None) if e is not None] + list(extra_exif)
    if not ifd0 and not exif and not gps:
        return None
    has_exif = bool(exif) or exif_pointer is not None
    placeholder = ifd0 + ([entry(IFD0_EXIF, exif_pointer_kind, pack(order, 'I', 0))] if has_exif else []) \
        + ([entry(IFD0_GPS, LONG, pack(order, 'I', 0))] if gps else [])
    table0, data0 = ifd(order, placeholder, 8)
    exif_start = 8 + len(table0) + len(data0)
    exif_table, exif_data = ifd(order, exif, exif_start) if exif else (b'', b'')
    gps_start = exif_start + len(exif_table) + len(exif_data)
    gps_table, gps_data = ifd(order, [ascii_entry(1, 'N')], gps_start) if gps else (b'', b'')
    real = ifd0 + ([entry(IFD0_EXIF, exif_pointer_kind, pack(order, 'I', exif_start if exif_pointer is None else exif_pointer))] if has_exif else []) \
        + ([entry(IFD0_GPS, LONG, pack(order, 'I', gps_start if gps_pointer_value is None else gps_pointer_value))] if gps else [])
    table0, data0 = ifd(order, real, 8, ifd0_next)
    header = (b'II*\0' if order == 'II' else b'MM\0*') + pack(order, 'I', 8)
    return b'Exif\0\0' + header + table0 + data0 + exif_table + exif_data + gps_table + gps_data


def dc_codes():
    """Standard JPEG luminance DC Huffman table (counts and symbols) and its canonical codes."""
    counts = [0, 1, 5, 1, 1, 1, 1, 1, 1, 0, 0, 0, 0, 0, 0, 0]
    symbols = list(range(12))
    codes, code, index = {}, 0, 0
    for length, count in enumerate(counts, 1):
        for _ in range(count):
            codes[symbols[index]] = (code, length)
            code += 1
            index += 1
        code <<= 1
    return counts, symbols, codes


def entropy(width, height, seed):
    _, _, codes = dc_codes()
    bits, previous = '', [0, 0, 0]
    for y in range((height + 7) // 8):
        for x in range((width + 7) // 8):
            for component in range(3):
                value = (x * 37 + y * 91 + component * 53 + seed) % 200 - 100
                diff, previous[component] = value - previous[component], value
                category = abs(diff).bit_length()
                code, length = codes[category]
                bits += format(code, '0%db' % length)
                if category:
                    bits += format(diff if diff >= 0 else diff + (1 << category) - 1, '0%db' % category)
                bits += '0'  # the one-symbol AC table: its only code (end of block)
    bits += '1' * (-len(bits) % 8)
    raw = bytes(int(bits[i:i + 8], 2) for i in range(0, len(bits), 8))
    return raw.replace(b'\xff', b'\xff\0')


def segment(marker, payload):
    return b'\xff' + bytes([marker]) + struct.pack('>H', len(payload) + 2) + payload


def build(width, height, seed=1, *, exif=None, trailing=b'', sof_marker=0xC0, precision=8, components=3, app1_count=1, app_segments=(), **spec):
    """Return JPEG bytes; ``spec`` selects the EXIF content (see ``exif_segment``)."""
    payload = exif if exif is not None else exif_segment(**spec)
    counts, symbols, _ = dc_codes()
    out = b'\xff\xd8' + segment(0xE0, b'JFIF\0\x01\x01\x00\x00\x01\x00\x01\x00\x00')
    if payload is not None:
        out += segment(0xE1, payload) * app1_count
    for marker, body in app_segments:
        out += segment(marker, body)
    out += segment(0xDB, b'\0' + bytes([1]) * 64)
    sof = bytes([precision]) + struct.pack('>HH', height, width) + bytes([components]) + b''.join(bytes([i + 1, 0x11, 0]) for i in range(components))
    out += segment(sof_marker, sof)
    out += segment(0xC4, b'\x00' + bytes(counts) + bytes(symbols))
    out += segment(0xC4, b'\x10' + bytes([1] + [0] * 15) + b'\x00')
    out += segment(0xDA, bytes([components]) + b''.join(bytes([i + 1, 0x00]) for i in range(components)) + b'\x00\x3f\x00')
    return out + entropy(width, height, seed) + b'\xff\xd9' + trailing


# ---------------------------------------------------------------- workbench fixtures (E1): general TIFF/EXIF, XMP and IPTC builders
BYTE, RATIONAL, UNDEFINED, SRATIONAL = 1, 5, 7, 10
SIZES = {BYTE: 1, ASCII: 1, SHORT: 2, LONG: 4, RATIONAL: 8, UNDEFINED: 1, SRATIONAL: 8}


def short_entry(order, tag, *values): return entry(tag, SHORT, b''.join(pack(order, 'H', v) for v in values))
def long_entry(order, tag, *values): return entry(tag, LONG, b''.join(pack(order, 'I', v) for v in values))
def byte_entry(tag, *values): return entry(tag, BYTE, bytes(values))
def undefined_entry(tag, raw): return entry(tag, UNDEFINED, raw)
def rational_entry(order, tag, *pairs): return entry(tag, RATIONAL, b''.join(pack(order, 'II', n, d) for n, d in pairs))
def srational_entry(order, tag, *pairs): return entry(tag, SRATIONAL, b''.join(pack(order, 'ii', n, d) for n, d in pairs))


def tiff_payload(order='II', ifd0=(), exif=(), gps=(), ifd1=(), dup_ifd0_cycle=False):
    """General Exif APP1 payload from entry lists (see ``entry``): IFD0, ExifIFD, GPS IFD and an optional IFD1 (placed last)."""
    ptr = lambda tag, value: entry(tag, LONG, pack(order, 'I', value))
    def lay(values):
        rows0 = list(ifd0) + ([ptr(IFD0_EXIF, values['exif'])] if exif else []) + ([ptr(IFD0_GPS, values['gps'])] if gps else [])
        t0, d0 = ifd(order, rows0, 8, values['ifd1'] if ifd1 else 0)
        cursor = 8 + len(t0) + len(d0)
        te, de = ifd(order, exif, cursor) if exif else (b'', b'')
        cursor_gps = cursor + len(te) + len(de)
        tg, dg = ifd(order, gps, cursor_gps) if gps else (b'', b'')
        cursor_1 = cursor_gps + len(tg) + len(dg)
        t1, d1 = ifd(order, ifd1, cursor_1) if ifd1 else (b'', b'')
        return t0 + d0, te + de, tg + dg, t1 + d1, {'exif': cursor if exif else 0, 'gps': cursor_gps if gps else 0, 'ifd1': cursor_1 if ifd1 else 0}
    values = lay({'exif': 0, 'gps': 0, 'ifd1': 0})[4]
    first, second, third, fourth, values = lay(values)
    header = (b'II*\0' if order == 'II' else b'MM\0*') + pack(order, 'I', 8)
    return b'Exif\0\0' + header + first + second + third + fourth


def xmp_packet(properties='', namespaces=None, wrapper=True, extra_description=''):
    """Standard XMP packet text (bytes); ``properties`` is the inside of one rdf:Description as XML text."""
    ns = {'rdf': 'http://www.w3.org/1999/02/22-rdf-syntax-ns#', 'dc': 'http://purl.org/dc/elements/1.1/', 'xmp': 'http://ns.adobe.com/xap/1.0/',
          'photoshop': 'http://ns.adobe.com/photoshop/1.0/', 'tiff': 'http://ns.adobe.com/tiff/1.0/', 'exif': 'http://ns.adobe.com/exif/1.0/',
          'xmpRights': 'http://ns.adobe.com/xap/1.0/rights/', 'aux': 'http://ns.adobe.com/exif/1.0/aux/'}
    ns.update(namespaces or {})
    declarations = ' '.join('xmlns:%s="%s"' % item for item in ns.items() if item[0] != 'rdf')
    body = ('<x:xmpmeta xmlns:x="adobe:ns:meta/"><rdf:RDF xmlns:rdf="%s"><rdf:Description rdf:about="" %s>%s</rdf:Description>%s</rdf:RDF></x:xmpmeta>'
            % (ns['rdf'], declarations, properties, extra_description))
    text = ('<?xpacket begin="﻿" id="W5M0MpCehiHzreSzNTczkc9d"?>' + body + '<?xpacket end="w"?>') if wrapper else body
    return text.encode('utf-8')


def xmp_app1(packet): return b'http://ns.adobe.com/xap/1.0/\0' + packet


def iptc_dataset(record, number, value):
    raw = value if isinstance(value, bytes) else value.encode('utf-8')
    return bytes([0x1C, record, number]) + struct.pack('>H', len(raw)) + raw


def iptc_app13(datasets, utf8=True):
    """Photoshop 3.0 APP13 with one 8BIM 0x0404 IPTC-NAA resource; 1:90 declares UTF-8 unless ``utf8`` is false."""
    body = (iptc_dataset(1, 90, b'\x1b%G') if utf8 else b'') + b''.join(iptc_dataset(*d) for d in datasets)
    pad = b'\0' if len(body) % 2 else b''
    return b'Photoshop 3.0\0' + b'8BIM' + struct.pack('>H', 0x0404) + b'\0\0' + struct.pack('>I', len(body)) + body + pad


# Literal expectations for the workbench corpus. Coordinates and places are invented (open-ocean point, no real site).
WORKBENCH_FIXTURES = {
    'ridge-line': dict(width=16, height=16, order='II', rich=dict(
        ifd0=['make:Northfield', 'model:NF-200', 'orientation:1', 'software:Synthetic fixture generator', 'artist:Ada Example', 'copyright:(c) 2024 Ada Example',
              'description:Ridge line at dusk'],
        exif=['original:2024:05:06 07:08:09', 'digitized:2024:05:06 07:08:10', 'subsec:12', 'offset:+02:00', 'exposure:1/250', 'fnumber:28/10', 'iso:200',
              'focal:350/10', 'lensmodel:NF 35mm f/1.8', 'bodyserial:SN-0001'],
        gps=['latref:N', 'lat:12,34,5/1', 'lonref:W', 'lon:45,40,0/1', 'altref:0', 'alt:1234/10', 'dirref:T', 'dir:905/10', 'datum:WGS-84',
             'gpsdate:2024:05:06', 'gpstime:5,8,9']),
        xmp=dict(description='Ridge line at dusk', title='Ridge', creator='Ada Example', rights='(c) 2024 Ada Example', subject=['ridge', 'dusk'],
                 created='2024-05-06T07:08:09+02:00', weburl='https://example.invalid/rights', rating=4),
        iptc=[(2, 5, 'Ridge'), (2, 25, 'ridge'), (2, 25, 'dusk'), (2, 55, '20240506'), (2, 60, '070809+0200'), (2, 80, 'Ada Example'),
              (2, 90, 'Imaginary Town'), (2, 101, 'Nowhereland'), (2, 116, '(c) 2024 Ada Example'), (2, 120, 'Ridge line at dusk')]),
    'harbour-light': dict(width=24, height=16, order='MM', rich=dict(
        ifd0=['make:Northfield', 'model:NF-200', 'orientation:6'],
        exif=['original:2024:05:07 18:30:00', 'offset:+02:00', 'exposure:1/60', 'fnumber:4/1', 'iso:800', 'focal:240/10', 'focal35:36', 'bias:-1/3'], gps=[])),
    'orchard-gate': dict(width=16, height=24, order='II', rich=dict(
        ifd0=['make:Riverside Optics', 'model:RB 7', 'orientation:1'],
        exif=['original:2024:05:08 09:15:30', 'offset:+02:00', 'exposure:1/500', 'fnumber:56/10', 'iso:100', 'focal:500/10', 'focal35:75', 'bias:0/1'], gps=[])),
    'conflict-desk': dict(width=8, height=8, order='MM', rich=dict(
        ifd0=['make:Riverside Optics', 'model:RB 7', 'artist:Ben Sample', 'description:Desk with a laptop'],
        exif=['original:2023:12:31 23:59:58'],
        gps=[]),
        xmp=dict(description='Desk with a notebook', creator='Cy Other', created='2023-12-31T23:59:59'),
        iptc=[(2, 120, 'Desk with a laptop'), (2, 80, 'Ben Sample')]),
    'latin-iptc': dict(width=8, height=8, order='II', rich=None, xmp=None,
                       iptc=[(2, 5, b'Caf\xe9'), (2, 120, 'Plain ascii text')], iptc_utf8=False),
    'utf8-iptc': dict(width=8, height=8, order='MM', rich=None, xmp=None,
                      iptc=[(2, 5, 'Café ☕'), (2, 25, 'café')]),
    'entity-xmp': dict(width=8, height=8, order='II', rich=None, iptc=None, raw_xmp=(
        '<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "boom">]><x:xmpmeta xmlns:x="adobe:ns:meta/"><rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">'
        '<rdf:Description xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:description>&a;</dc:description></rdf:Description></rdf:RDF></x:xmpmeta>')),
    'duplicate-tags': dict(width=8, height=8, order='II', rich=dict(ifd0=['make:First', 'make:Second', 'model:Twin'], exif=[], gps=[])),
    'lens-record': dict(width=8, height=8, order='MM', rich=dict(
        ifd0=['make:Northfield', 'model:NF-300', 'modified:2024:05:06 08:00:00'],
        exif=['lensmake:Northfield Optics', 'lensmodel:NF 85mm f/1.4', 'lensserial:LS-0042'], gps=[])),
    # GPS references: southern/western/below-sea, zero values that still carry references, and an altitude without any reference tag
    'south-west-sea': dict(width=8, height=8, order='II', rich=dict(ifd0=['make:Southwind', 'model:SW-1'], exif=[],
        gps=['latref:S', 'lat:33,51,0/1', 'lonref:W', 'lon:151,12,30/1', 'altref:1', 'alt:25/1'])),
    'zero-refs': dict(width=8, height=8, order='MM', rich=dict(ifd0=['make:Southwind', 'model:SW-2'], exif=[],
        gps=['latref:S', 'lat:0,0,0/1', 'lonref:W', 'lon:0,0,0/1', 'altref:1', 'alt:0/1'])),
    'default-altitude': dict(width=8, height=8, order='II', rich=dict(ifd0=['make:Southwind', 'model:SW-3'], exif=[],
        gps=['latref:N', 'lat:1,0,0/1', 'lonref:E', 'lon:2,30,0/1', 'alt:5/1'])),
    # rationals whose native 10-digit rendering is a tiny number or a zero
    'near-zero': dict(width=8, height=8, order='MM', rich=dict(ifd0=['make:Southwind', 'model:SW-4'],
        exif=['exposure:1/8000', 'fnumber:1/4294967295', 'focal:0/1', 'bias:-1/2147483647'], gps=[])),
    # a malformed EXIF capture time beside a valid XMP capture time
    'mixed-sources': dict(width=8, height=8, order='II', rich=dict(ifd0=['make:Southwind', 'model:SW-5'], exif=['original:2024:13:45 25:61:61'], gps=[]),
                          xmp=dict(created='2024-05-06T07:08:09+02:00')),
    # a repeated GPS reference tag (different copies, identical copies, and a repeated altitude reference); the rest of the GPS IFD is valid
    'repeated-lat-ref': dict(width=8, height=8, order='II', rich=dict(ifd0=['make:Southwind', 'model:SW-6'], exif=[],
        gps=['latref:N', 'latref:S', 'lat:10,0,0/1', 'lonref:E', 'lon:20,0,0/1', 'altref:0', 'alt:7/1'])),
    'repeated-lon-ref': dict(width=8, height=8, order='MM', rich=dict(ifd0=['make:Southwind', 'model:SW-7'], exif=[],
        gps=['latref:S', 'lat:11,0,0/1', 'lonref:E', 'lonref:E', 'lon:21,0,0/1', 'altref:0', 'alt:8/1'])),
    'repeated-alt-ref': dict(width=8, height=8, order='II', rich=dict(ifd0=['make:Southwind', 'model:SW-8'], exif=[],
        gps=['latref:N', 'lat:12,0,0/1', 'lonref:W', 'lon:22,0,0/1', 'altref:0', 'altref:1', 'alt:9/1'])),
}
SIDECARS = {
    'sidecar-only': dict(properties='<dc:description><rdf:Alt><rdf:li xml:lang="x-default">Described only in a sidecar</rdf:li></rdf:Alt></dc:description>'
                         '<dc:creator><rdf:Seq><rdf:li>Dee Sidecar</rdf:li></rdf:Seq></dc:creator><xmp:Rating>3</xmp:Rating>'
                         '<photoshop:DateCreated>2022-08-09T10:11:12</photoshop:DateCreated>'),
}
SIDECAR_PAIR = {'quay-side': dict(width=8, height=8, order='II', rich=dict(ifd0=['make:Northfield', 'model:NF-100'], exif=[], gps=[]), xmp=None, iptc=None,
                                  sidecar=dict(properties='<dc:description><rdf:Alt><rdf:li xml:lang="x-default">Quay at noon</rdf:li></rdf:Alt></dc:description>'))}


def rich_entries(order, spec):
    """Expand the literal ``name:value`` rows of a rich fixture into IFD entries (the table here is the only vocabulary)."""
    def split(row): name, _, value = row.partition(':'); return name, value
    def pairs(text): return [tuple(int(x) for x in part.split('/')) if '/' in part else (int(part), 1) for part in text.split(',')]
    ifd0, exif, gps = [], [], []
    for row in spec.get('ifd0', ()):
        k, v = split(row)
        ifd0.append({'make': lambda: ascii_entry(IFD0_MAKE, v), 'model': lambda: ascii_entry(IFD0_MODEL, v), 'orientation': lambda: short_entry(order, IFD0_ORIENTATION, int(v)),
                     'software': lambda: ascii_entry(IFD0_SOFTWARE, v), 'artist': lambda: ascii_entry(0x013B, v), 'copyright': lambda: ascii_entry(0x8298, v),
                     'description': lambda: ascii_entry(0x010E, v), 'modified': lambda: ascii_entry(0x0132, v)}[k]())
    for row in spec.get('exif', ()):
        k, v = split(row)
        exif.append({'original': lambda: ascii_entry(EXIF_ORIGINAL, v), 'digitized': lambda: ascii_entry(0x9004, v), 'subsec': lambda: ascii_entry(0x9291, v),
                     'offset': lambda: ascii_entry(EXIF_OFFSET, v), 'exposure': lambda: rational_entry(order, 0x829A, *pairs(v)), 'fnumber': lambda: rational_entry(order, 0x829D, *pairs(v)),
                     'iso': lambda: short_entry(order, 0x8827, int(v)), 'focal': lambda: rational_entry(order, 0x920A, *pairs(v)), 'lensmodel': lambda: ascii_entry(0xA434, v),
                     'bodyserial': lambda: ascii_entry(0xA431, v), 'lensmake': lambda: ascii_entry(0xA433, v), 'lensserial': lambda: ascii_entry(0xA435, v), 'focal35': lambda: short_entry(order, 0xA405, int(v)), 'bias': lambda: srational_entry(order, 0x9204, *pairs(v))}[k]())
    for row in spec.get('gps', ()):
        k, v = split(row)
        gps.append({'latref': lambda: ascii_entry(1, v), 'lat': lambda: rational_entry(order, 2, *pairs(v)), 'lonref': lambda: ascii_entry(3, v), 'lon': lambda: rational_entry(order, 4, *pairs(v)),
                    'altref': lambda: byte_entry(5, int(v)), 'alt': lambda: rational_entry(order, 6, *pairs(v)), 'gpstime': lambda: rational_entry(order, 7, *pairs(v)),
                    'datum': lambda: ascii_entry(18, v), 'dirref': lambda: ascii_entry(16, v), 'dir': lambda: rational_entry(order, 17, *pairs(v)),
                    'gpsdate': lambda: ascii_entry(29, v)}[k]())
    return ifd0, exif, gps


def xmp_properties(spec):
    def alt(tag, text): return '<%s><rdf:Alt><rdf:li xml:lang="x-default">%s</rdf:li></rdf:Alt></%s>' % (tag, text, tag)
    def seq(tag, items, kind='Seq'): return '<%s><rdf:%s>%s</rdf:%s></%s>' % (tag, kind, ''.join('<rdf:li>%s</rdf:li>' % i for i in items), kind, tag)
    out = ''
    if 'description' in spec: out += alt('dc:description', spec['description'])
    if 'title' in spec: out += alt('dc:title', spec['title'])
    if 'creator' in spec: out += seq('dc:creator', [spec['creator']])
    if 'rights' in spec: out += alt('dc:rights', spec['rights'])
    if 'subject' in spec: out += seq('dc:subject', spec['subject'], 'Bag')
    if 'created' in spec: out += '<photoshop:DateCreated>%s</photoshop:DateCreated>' % spec['created']
    if 'weburl' in spec: out += '<xmpRights:WebStatement>%s</xmpRights:WebStatement>' % spec['weburl']
    if 'rating' in spec: out += '<xmp:Rating>%d</xmp:Rating>' % spec['rating']
    return out


def workbench_jpeg(name, seed):
    spec = WORKBENCH_FIXTURES[name]
    order = spec['order']
    segments = []
    rich = spec.get('rich')
    payload = None
    if rich is not None:
        ifd0, exif, gps = rich_entries(order, rich)
        payload = tiff_payload(order, ifd0, exif, gps)
    if spec.get('xmp'): segments.append((0xE1, xmp_app1(xmp_packet(xmp_properties(spec['xmp'])))))
    if spec.get('raw_xmp'): segments.append((0xE1, xmp_app1(spec['raw_xmp'].encode('utf-8'))))
    if spec.get('iptc'): segments.append((0xED, iptc_app13(spec['iptc'], spec.get('iptc_utf8', True))))
    return build(spec['width'], spec['height'], seed, exif=payload, app_segments=segments)


def baseline_jpeg(name):
    """The bytes of one baseline fixture exactly as ``write`` makes them."""
    for seed, (candidate, spec) in enumerate(FIXTURES.items(), 1):
        if candidate == name:
            spec = dict(spec)
            return build(spec.pop('width'), spec.pop('height'), seed, **spec)
    raise KeyError(name)


def padded_make(data):
    """Same-size edit of the Make value ``Northfield\\0`` to ``Northfiel \\0``: a reader that keeps the trailing space and ExifTool, which trims it, disagree."""
    assert data.count(b'Northfield\0') == 1
    return data.replace(b'Northfield\0', b'Northfiel \0')


def workbench_files():
    """Every workbench fixture as {file name: bytes}; deterministic."""
    files = {}
    for seed, name in enumerate(WORKBENCH_FIXTURES, 101): files[name + '.jpg'] = workbench_jpeg(name, seed)
    files['padded-make.jpg'] = padded_make(baseline_jpeg('north-gate'))
    for name, spec in SIDECARS.items(): files[name + '.xmp'] = xmp_packet(spec['properties'])
    for seed, (name, spec) in enumerate(SIDECAR_PAIR.items(), 201):
        ifd0, exif, gps = rich_entries(spec['order'], spec['rich'])
        files[name + '.jpg'] = build(spec['width'], spec['height'], seed, exif=tiff_payload(spec['order'], ifd0, exif, gps))
        files[name + '.xmp'] = xmp_packet(spec['sidecar']['properties'])
    return files


# ---------------------------------------------------------------- write-family fixtures (E2): JPEGs to edit and to remove metadata from
# Structure only: scans are synthetic entropy bytes (stuffing, restart markers, DHT/SOS between scans); no file is a decodable photograph, and
# expectations are literal in the tests, never taken from ExifTool.
def edit_icc():
    """A 152-byte synthetic ICC profile (one tag) split into two APP2 chunks."""
    icc = bytearray(152)
    icc[0:4] = struct.pack('>I', 152); icc[8:12] = b'\x02\x10\x00\x00'; icc[12:16] = b'mntr'; icc[16:20] = b'RGB '; icc[20:24] = b'XYZ '; icc[36:40] = b'acsp'
    icc[128:132] = struct.pack('>I', 1); icc[132:144] = b'cprt' + struct.pack('>II', 144, 8); icc[144:152] = b'text\0\0\0\0'
    icc = bytes(icc)
    return [(0xE2, b'ICC_PROFILE\0\x01\x02' + icc[:80]), (0xE2, b'ICC_PROFILE\0\x02\x02' + icc[80:])]


def thumbnail_jpeg(): return build(2, 2, 9)


def entropy_bytes(seed, count, restarts=False):
    state, out, rst = seed, bytearray(), 0
    while len(out) < count:
        state = (state * 1103515245 + 12345) & 0x7FFFFFFF
        b = (state >> 16) & 0xFF
        if restarts and len(out) % 17 == 16:
            out += bytes([0xFF, 0xD0 + rst % 8]); rst += 1
        elif len(out) % 11 == 10:
            out += b'\xff\x00'
        else:
            out.append(b)
            if b == 0xFF: out.append(0)
    return bytes(out)


def edit_scans(base, *, process=0xC2, scans=1, restarts=False, between_tables=True, dri=None):
    """Re-frame a baseline fixture as another frame process with several synthetic scans (structure only)."""
    sos_at = base.index(b'\xff\xda')
    head = base[:sos_at].replace(b'\xff\xc0', bytes([0xFF, process]), 1)
    if dri is not None: head += segment(0xDD, struct.pack('>H', dri))
    out = head
    for k in range(scans):
        if between_tables and k: out += segment(0xC4, b'\x10' + bytes([1] + [0] * 15) + b'\x00')
        out += segment(0xDA, bytes([3, 1, 0, 2, 0, 3, 0, 0, 63, 0])) + entropy_bytes(40 + k, 60, restarts)
    return out + b'\xff\xd9'


def edit_fixture(order='II', *, orientation=6, gps=True, thumb=True, maker=False, icc=True, adobe=True, comment=True, exif=True, xmp=True, iptc=True, iptc_utf8=True, iptc_sets=None,
                 xmp_properties=None, ifd0_extra=(), seed=301, copyright_editor=False, exif_entries=(), ifd0_entries=()):
    ifd0 = ['make:Northfield', 'model:NF-200', 'orientation:%d' % orientation, 'software:Synthetic fixture generator', 'artist:Old Artist', 'copyright:Old Copyright', 'description:Old description', 'modified:2024:05:06 08:00:00', *ifd0_extra]
    exif_rows = ['original:2024:05:06 07:08:09', 'bodyserial:SN-0001', 'lensserial:LS-0002']
    gps_rows = ['latref:N', 'lat:12,34,5/1', 'lonref:W', 'lon:45,40,0/1'] if gps else []
    i0, ex, gp = rich_entries(order, dict(ifd0=ifd0, exif=exif_rows, gps=gps_rows))
    if copyright_editor:
        i0 = [e for e in i0 if e[0] != 0x8298] + [ascii_entry(0x8298, 'Photographer Name')]
        i0[-1] = entry(0x8298, ASCII, b'Photographer Name\0Editor Name\0')
    if maker: ex.append(undefined_entry(0x927C, b'MAKERNOTE-OPAQUE-0123456789'))
    ex, i0 = list(ex) + list(exif_entries), list(i0) + list(ifd0_entries)           # optional raw entries (tests build rendering-metadata variants); absent by default
    thumb_bytes = thumbnail_jpeg()

    def payload(offset):
        ifd1 = [short_entry(order, 0x0103, 6), long_entry(order, 0x0201, offset), long_entry(order, 0x0202, len(thumb_bytes))] if thumb else ()
        return tiff_payload(order, i0, ex, gp, ifd1)
    body = payload(0)
    if thumb:
        body = payload(len(body) - 6) + thumb_bytes
    segments = []
    if adobe: segments.append((0xEE, b'Adobe\0\x64\x00\x00\x00\x00\x01'))
    if icc: segments += edit_icc()
    if comment: segments.append((0xFE, b'a synthetic comment'))
    if xmp:
        props = xmp_properties if xmp_properties is not None else (
            '<dc:title><rdf:Alt><rdf:li xml:lang="x-default">Old title</rdf:li></rdf:Alt></dc:title><exif:GPSLatitude>12,34.0833N</exif:GPSLatitude><photoshop:City>Imaginary Town</photoshop:City><tiff:Make>Northfield</tiff:Make>'
            '<iptcExt:LocationShown><rdf:Bag><rdf:li rdf:parseType="Resource"><iptcExt:City>Shown City</iptcExt:City></rdf:li></rdf:Bag></iptcExt:LocationShown>')
        segments.append((0xE1, xmp_app1(xmp_packet(props, namespaces={'iptcExt': 'http://iptc.org/std/Iptc4xmpExt/2008-02-12/'}))))
    if iptc:
        sets = iptc_sets if iptc_sets is not None else [(2, 5, 'Old title'), (2, 90, 'Imaginary Town'), (2, 25, 'k1'), (2, 80, 'Old Artist'), (2, 120, 'Old description')]
        segments.append((0xED, iptc_app13(sets, iptc_utf8)))
    return build(8, 8, seed, exif=body if exif else None, app_segments=segments)


def alt(tag, items):
    return '<%s><rdf:Alt>%s</rdf:Alt></%s>' % (tag, ''.join('<rdf:li xml:lang="%s">%s</rdf:li>' % kv for kv in items), tag)


def bag(tag, items, kind='Bag'):
    return '<%s><rdf:%s>%s</rdf:%s></%s>' % (tag, kind, ''.join('<rdf:li>%s</rdf:li>' % i for i in items), kind, tag)


def edit_files():
    """Every write-family fixture as {file name: bytes}; deterministic."""
    files = {}
    files['edit-rich.jpg'] = edit_fixture(seed=301)
    files['edit-rich-mm.jpg'] = edit_fixture('MM', orientation=8, seed=302)
    files['edit-jfif-only.jpg'] = build(8, 8, 303)
    files['edit-no-iptc.jpg'] = edit_fixture(iptc=False, seed=304)
    files['edit-maker.jpg'] = edit_fixture(maker=True, seed=305)
    files['edit-copyright-editor.jpg'] = edit_fixture(copyright_editor=True, seed=306)
    files['edit-legacy-iptc.jpg'] = edit_fixture(iptc_utf8=False, iptc_sets=[(2, 5, b'Caf\xe9'), (2, 80, 'Old Artist'), (2, 120, 'Plain description')], seed=307)
    files['edit-ascii-iptc.jpg'] = edit_fixture(iptc_utf8=False, iptc_sets=[(2, 5, 'Plain title'), (2, 80, 'Old Artist'), (2, 120, 'Plain description')], seed=308)
    files['edit-languages.jpg'] = edit_fixture(xmp_properties=alt('dc:title', [('x-default', 'Old title'), ('de', 'Alter Titel'), ('fr', 'Ancien titre')]) + alt('dc:description', [('x-default', 'Old description'), ('de', 'Alte Beschreibung')]), seed=309)
    files['edit-keywords.jpg'] = edit_fixture(xmp_properties=bag('dc:subject', ['alpine', 'dawn', 'draft']), iptc_sets=[(2, 25, 'alpine'), (2, 25, 'dawn'), (2, 25, 'draft')], seed=310)
    files['edit-keywords-conflict.jpg'] = edit_fixture(xmp_properties=bag('dc:subject', ['alpine', 'dawn']), iptc_sets=[(2, 25, 'alpine'), (2, 25, 'other')], seed=311)
    files['edit-trailer.jpg'] = edit_fixture(seed=312) + b'TRAILING-BYTES-AFTER-EOI'
    base = build(8, 8, 313, exif=tiff_payload('II', *[rich_entries('II', dict(ifd0=['make:Northfield', 'model:NF-200', 'orientation:6'], exif=[], gps=[]))[0]]), app_segments=[(0xE1, xmp_app1(xmp_packet(alt('dc:title', [('x-default', 'Progressive title')]))))])
    files['edit-progressive.jpg'] = edit_scans(base, process=0xC2, scans=10, restarts=True, dri=3)
    files['edit-restart.jpg'] = edit_scans(base, process=0xC0, scans=1, restarts=True, dri=1)
    files['edit-multiscan.jpg'] = edit_scans(base, process=0xC0, scans=3, restarts=False)
    return files


def write(directory):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=False)
    for seed, (name, spec) in enumerate(FIXTURES.items(), 1):
        spec = dict(spec)
        (directory / (name + '.jpg')).write_bytes(build(spec.pop('width'), spec.pop('height'), seed, **spec))
    for name, data in {**workbench_files(), **edit_files()}.items():
        (directory / name).write_bytes(data)


if __name__ == '__main__':
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    write(sys.argv[1])
