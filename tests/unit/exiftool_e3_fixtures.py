"""Synthetic JPEG authoring for the E3 time and location tests (standard library only; every file is hand-built from raw TIFF, XMP and IIM entries).

One builder covers the three time families (EXIF, XMP, IPTC), the GPS IFD in any metadata edition, XMP GPS properties and the JFIF density, so each test states
its fixture as a literal and never derives an expectation from the code under test or from ExifTool.
"""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools'))

import author_exiftool_fixtures as a  # noqa: E402

O = 'II'
JFIF = a.segment(0xE0, b'JFIF\0\x01\x01\x00\x00\x01\x00\x01\x00\x00')


def xmp_date(value):
    return value


def xmp_properties(*, captured=None, created=None, modified=None, exif_dto=None, lat=None, lon=None, altitude=None, altitude_ref=None, datum=None, extra=''):
    """XMP property text (one rdf:Description) from literal XMP values."""
    out = []
    if captured is not None:
        out.append('<photoshop:DateCreated>%s</photoshop:DateCreated>' % captured)
    if exif_dto is not None:
        out.append('<exif:DateTimeOriginal>%s</exif:DateTimeOriginal>' % exif_dto)
    if created is not None:
        out.append('<xmp:CreateDate>%s</xmp:CreateDate>' % created)
    if modified is not None:
        out.append('<xmp:ModifyDate>%s</xmp:ModifyDate>' % modified)
    for name, value in (('GPSLatitude', lat), ('GPSLongitude', lon), ('GPSAltitude', altitude), ('GPSAltitudeRef', altitude_ref), ('GPSMapDatum', datum)):
        if value is not None:
            out.append('<exif:%s>%s</exif:%s>' % (name, value, name))
    return ''.join(out) + extra


def jpeg(*, make='A', model='M', serial=None, exif=True, exif_version=b'0300', dto='2026:03:01 12:00:00', create=None, modify=None, off='+01:00', off_create=None, off_modify=None,
         sub='12', sub_create=None, sub_modify=None, gps=None, xmp=None, iptc=None, jfif=True, ifd0_extra=(), exif_extra=(), gps_extra=(), seed=1):
    """A 16x16 baseline JPEG. ``gps`` is a dict (see ``gps_entries``) or ``None``; ``xmp`` is XMP property text; ``iptc`` a list of ``(record, dataset, value)``;
    ``jfif`` is ``True``, ``False`` or ``(units, xdensity, ydensity)``."""
    segments = []
    payload = None
    if exif:
        ifd0 = [a.ascii_entry(0x010F, make), a.ascii_entry(0x0110, model)]
        if modify:
            ifd0.append(a.ascii_entry(0x0132, modify))
        ifd0 += list(ifd0_extra)
        ex = []
        if exif_version is not None:
            ex.append(a.undefined_entry(0x9000, exif_version))
        for tag, value in ((0x9003, dto), (0x9004, create), (0x9010, off_modify), (0x9011, off), (0x9012, off_create), (0x9290, sub_modify), (0x9291, sub), (0x9292, sub_create), (0xA431, serial)):
            if value:
                ex.append(a.ascii_entry(tag, value))
        ex += list(exif_extra)
        payload = a.tiff_payload(O, ifd0, ex, gps_entries(gps) + list(gps_extra) if gps is not None else list(gps_extra))
    if xmp is not None:
        segments.append((0xE1, a.xmp_app1(a.xmp_packet(xmp))))
    if iptc is not None:
        segments.append((0xED, a.iptc_app13(iptc)))
    data = a.build(16, 16, seed, exif=payload, app_segments=segments)
    if jfif is not True:
        data = data.replace(JFIF, b'' if jfif is False else a.segment(0xE0, b'JFIF\0\x01\x01' + bytes([jfif[0]]) + jfif[1].to_bytes(2, 'big') + jfif[2].to_bytes(2, 'big') + b'\x00\x00'), 1)
    return data


def gps_entries(gps):
    """GPS IFD entries of a dict: ``version`` (tuple), ``lat``/``lon`` (three ``(n, d)`` pairs) with ``lat_ref``/``lon_ref``, ``alt`` ``(n, d)`` with ``alt_ref``, ``datum``,
    ``error`` ``(n, d)``, ``date`` text, ``time`` three pairs, ``direction`` ``(n, d)`` with ``direction_ref``, ``extra`` raw entries."""
    rows = []
    if gps.get('version') is not None:
        rows.append(a.byte_entry(0, *gps['version']))
    if 'lat' in gps:
        rows += [a.ascii_entry(1, gps.get('lat_ref', 'N')), a.rational_entry(O, 2, *gps['lat'])]
    if 'lon' in gps:
        rows += [a.ascii_entry(3, gps.get('lon_ref', 'E')), a.rational_entry(O, 4, *gps['lon'])]
    if gps.get('alt_ref') is not None:
        rows.append(a.byte_entry(5, gps['alt_ref']))
    if gps.get('alt') is not None:
        rows.append(a.rational_entry(O, 6, gps['alt']))
    if gps.get('time') is not None:
        rows.append(a.rational_entry(O, 7, *gps['time']))
    if gps.get('datum'):
        rows.append(a.ascii_entry(0x12, gps['datum']))
    if gps.get('direction') is not None:
        rows += [a.ascii_entry(0x10, gps.get('direction_ref', 'T')), a.rational_entry(O, 0x11, gps['direction'])]
    if gps.get('date'):
        rows.append(a.ascii_entry(0x1D, gps['date']))
    if gps.get('error') is not None:
        rows.append(a.rational_entry(O, 0x1F, gps['error']))
    rows += list(gps.get('extra', ()))
    return rows


TOKYO = {'version': (2, 3, 0, 0), 'lat': ((35, 1), (30, 1), (0, 1)), 'lon': ((139, 1), (15, 1), (0, 1)), 'alt': (523, 10), 'alt_ref': 0, 'datum': 'WGS-84'}


def full_time(**kw):
    """The standard three-family time fixture: EXIF 12:00:00 +01:00 .12, the same wall time in XMP photoshop:DateCreated and in IPTC 2:55/2:60."""
    base = dict(dto='2026:03:01 12:00:00', off='+01:00', sub='12', xmp=xmp_properties(captured='2026-03-01T12:00:00.12+01:00'), iptc=[(2, 55, '20260301'), (2, 60, '120000+0100')])
    base.update(kw)
    return jpeg(**base)


# ---------------------------------------------------------------- reading outputs back with the standard-library walkers (never through ExifTool and never through the catalogue)
def _payloads(data):
    sys.path.insert(0, str(ROOT / 'src'))
    from schemaxis.adaptors.exiftool import containers, records
    return records.Payloads(containers.locate(data))


def exif_entry(data, ifd, tag):
    """The single raw ``Entry`` of one IFD tag of a file, or ``None`` (absent IFD or tag)."""
    state = _payloads(data).exif
    if state[0] != 'ok':
        return None
    group = state[1]['ifds'].get(ifd)
    found = [e for e in group[1] if e.tag == tag] if group and group[0] == 'ok' else []
    assert len(found) <= 1, (ifd, tag, len(found))
    return found[0] if found else None


def exif_ascii(data, ifd, tag):
    e = exif_entry(data, ifd, tag)
    return None if e is None else e.raw.rstrip(b'\0').decode('ascii')


def exif_rationals(data, ifd, tag):
    e = exif_entry(data, ifd, tag)
    return None if e is None else [tuple(v) for v in e.values()]


def exif_bytes(data, ifd, tag):
    e = exif_entry(data, ifd, tag)
    return None if e is None else e.values()


def exif_tags(data, ifd):
    state = _payloads(data).exif
    group = state[1]['ifds'].get(ifd) if state[0] == 'ok' else None
    return sorted(e.tag for e in group[1]) if group and group[0] == 'ok' else []


def xmp_value(data, prop):
    """The text of one XMP property (a single simple occurrence), or ``None``."""
    state = _payloads(data).xmp
    found = state[1].get(prop) if state[0] == 'ok' else None
    assert not found or len(found) == 1, prop
    return None if not found else found[0].get('value')


def xmp_names(data):
    state = _payloads(data).xmp
    return sorted(state[1]) if state[0] == 'ok' else []


def iim_value(data, record, dataset):
    state = _payloads(data).iptc
    found = state[1]['datasets'].get((record, dataset)) if state[0] == 'ok' else None
    return None if not found else found[0].decode('ascii')
