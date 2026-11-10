"""Deterministic XMP sidecar serializer of ``exportSidecar`` (host-only, standard library, closed 29-property set).

The serializer writes only selected, typed, present facts of one item. It knows exactly the properties below, in this order, with one ``rdf:Description``
and a fixed namespace order; it never copies a packet, never merges an existing sidecar and never writes an unknown property. Output is UTF-8 with LF line
endings, an xpacket wrapper the way ExifTool writes it, no padding and no ``x:xmptk`` (this is not ExifTool output and does not claim to be).

``expected(model)`` states, separately from the text emitter, what the hardened reader must find in the bytes (the property -> occurrence mapping); the
proof re-reads the bytes with the independent reader and compares to it. ``NATIVE`` is the pinned map of each property to the key ExifTool 13.55 lists it
under (the fixed listing runs ``-G0:1:4 -n -e``), used to anchor every produced property.
"""
from fractions import Fraction
import re

MAX_BYTES = 1024 * 1024
HEADER = '<?xpacket begin="﻿" id="W5M0MpCehiHzreSzNTczkc9d"?>\n<x:xmpmeta xmlns:x="adobe:ns:meta/">\n<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">\n'
FOOTER = '</rdf:RDF>\n</x:xmpmeta>\n<?xpacket end="w"?>\n'
NAMESPACES = (('dc', 'http://purl.org/dc/elements/1.1/'), ('xmp', 'http://ns.adobe.com/xap/1.0/'), ('xmpRights', 'http://ns.adobe.com/xap/1.0/rights/'),
              ('photoshop', 'http://ns.adobe.com/photoshop/1.0/'), ('tiff', 'http://ns.adobe.com/tiff/1.0/'), ('exif', 'http://ns.adobe.com/exif/1.0/'),
              ('exifEX', 'http://cipa.jp/exif/1.0/'))
# (model key, property, form, native listing key); the order is the order of emission
ROWS = (('title', 'dc:title', 'alt', 'XMP-dc:Title'), ('description', 'dc:description', 'alt', 'XMP-dc:Description'), ('copyright', 'dc:rights', 'alt', 'XMP-dc:Rights'),
        ('keywords', 'dc:subject', 'bag', 'XMP-dc:Subject'), ('creator', 'dc:creator', 'seq', 'XMP-dc:Creator'),
        ('rightsUrl', 'xmpRights:WebStatement', 'text', 'XMP-xmpRights:WebStatement'), ('rating', 'xmp:Rating', 'integer', 'XMP-xmp:Rating'),
        ('locationCity', 'photoshop:City', 'text', 'XMP-photoshop:City'), ('locationCountry', 'photoshop:Country', 'text', 'XMP-photoshop:Country'),
        ('captureTime', 'photoshop:DateCreated', 'date', 'XMP-photoshop:DateCreated'),
        ('cameraMake', 'tiff:Make', 'text', 'XMP-tiff:Make'), ('cameraModel', 'tiff:Model', 'text', 'XMP-tiff:Model'),
        ('lensMake', 'exifEX:LensMake', 'text', 'XMP-exifEX:LensMake'), ('lensModel', 'exifEX:LensModel', 'text', 'XMP-exifEX:LensModel'),
        ('bodySerialNumber', 'exifEX:BodySerialNumber', 'text', 'XMP-exifEX:SerialNumber'), ('lensSerialNumber', 'exifEX:LensSerialNumber', 'text', 'XMP-exifEX:LensSerialNumber'),
        ('exposureTime', 'exif:ExposureTime', 'rational', 'XMP-exif:ExposureTime'), ('fNumber', 'exif:FNumber', 'rational', 'XMP-exif:FNumber'),
        ('focalLength', 'exif:FocalLength', 'rational', 'XMP-exif:FocalLength'), ('exposureBias', 'exif:ExposureBiasValue', 'rational', 'XMP-exif:ExposureCompensation'),
        ('focalLength35mm', 'exif:FocalLengthIn35mmFilm', 'integer', 'XMP-exif:FocalLengthIn35mmFormat'), ('isoSpeed', 'exifEX:PhotographicSensitivity', 'integer', 'XMP-exifEX:PhotographicSensitivity'),
        ('captureTimeExif', 'exif:DateTimeOriginal', 'date', 'XMP-exif:DateTimeOriginal'),
        ('gpsLatitude', 'exif:GPSLatitude', 'coordinate', 'XMP-exif:GPSLatitude'), ('gpsLongitude', 'exif:GPSLongitude', 'coordinate', 'XMP-exif:GPSLongitude'),
        ('gpsAltitude', 'exif:GPSAltitude', 'rational', 'XMP-exif:GPSAltitude'), ('gpsDatum', 'exif:GPSMapDatum', 'text', 'XMP-exif:GPSMapDatum'),
        ('gpsAltitudeRef', 'exifEX:GPSAltitudeRef', 'integer', 'XMP-exifEX:GPSAltitudeRef'), ('gpsDateTime', 'exif:GPSTimeStamp', 'gpsTime', 'XMP-exif:GPSDateTime'))
NATIVE = {prop: key for _, prop, _, key in ROWS}
PROPERTIES = tuple(prop for _, prop, _, _ in ROWS)
PRESENT = re.compile(r'[\x00-\x08\x0b\x0c\x0e-\x1f￾￿\ud800-\udfff]')


class SidecarError(ValueError):
    def __init__(self, code, message, **observed):
        super().__init__(message)
        self.code, self.message, self.observed = code, message, observed


def escape(text, where):
    found = PRESENT.search(text)
    if found:
        raise SidecarError('SIDECAR_TEXT_NOT_XML', 'a value holds a character XML 1.0 cannot carry (never stripped)', property=where, codePoint='U+%04X' % ord(found.group()), position=found.start())
    return text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('"', '&quot;').replace("'", '&apos;').replace('\r', '&#13;')


# ---------------------------------------------------------------- typed value forms
def rational_text(pair):
    n, d = pair
    return '%d/%d' % (n, d)


def coordinate_literal(components, ref):
    """``(literal, quantisation)`` of a stored coordinate: ``DDD,MM,SSk`` iff all denominators are 1 and minutes and seconds are below 60, otherwise ``DDD,MM.mmk`` (half-even, 8 digits)."""
    (dn, dd), (mn, md), (sn, sd) = components
    if dd == md == sd == 1 and 0 <= mn < 60 and 0 <= sn < 60:
        return '%d,%d,%d%s' % (dn, mn, sn, ref), None
    total = Fraction(dn, dd) + Fraction(mn, md) / 60 + Fraction(sn, sd) / 3600
    whole = total.numerator // total.denominator
    scaled = (total - whole) * 60 * 10 ** 8
    low = scaled.numerator // scaled.denominator
    rest = scaled - low
    rounded = low + (1 if rest > Fraction(1, 2) or (rest == Fraction(1, 2) and low % 2) else 0)
    minutes, fraction = divmod(rounded, 10 ** 8)
    if minutes >= 60:                                # rounding carried into the next degree
        whole, minutes = whole + 1, 0
    tail = ('%08d' % fraction).rstrip('0') or '0'
    written = whole + Fraction(minutes * 10 ** 8 + fraction, 10 ** 8) / 60
    return '%d,%d.%s%s' % (whole, minutes, tail, ref), {'stored': float(total), 'written': float(written), 'differenceArcSeconds': float(abs(total - written) * 3600)}


def date_literal(parts):
    """ISO 8601 of the recorded wall time: local time, optional fraction and optional offset (no zone is invented)."""
    text = parts['local']
    if parts.get('sub'):
        text += '.' + parts['sub']
    if parts.get('offset'):
        text += parts['offset']
    return text


def value_text(form, value, where):
    if form == 'text':
        return value
    if form == 'integer':
        return str(value)
    if form == 'rational':
        return rational_text(value)
    if form == 'date':
        return date_literal(value)
    if form == 'coordinate':
        return coordinate_literal(value['components'], value['ref'])[0]
    if form == 'gpsTime':
        return value
    raise SidecarError('SIDECAR_FORM_UNKNOWN', 'unknown property form', property=where)


# ---------------------------------------------------------------- the serializer
def build(model):
    """The sidecar bytes of ``model`` (a mapping from model keys of ``ROWS`` to typed values; absent keys are not written)."""
    unknown = sorted(set(model) - {k for k, _, _, _ in ROWS})
    if unknown:
        raise SidecarError('SIDECAR_MODEL_INVALID', 'the model holds a key this serializer does not know', keys=unknown)
    body, used = [], set()
    for key, prop, form, _ in ROWS:
        if key not in model:
            continue
        value = model[key]
        used.add(prop.partition(':')[0])
        if form == 'alt':
            items = [('x-default', value['text'])] + [(e['language'], e['text']) for e in value.get('languages', [])]
            inner = ''.join('<rdf:li xml:lang="%s">%s</rdf:li>' % (escape(lang, prop), escape(text, prop)) for lang, text in items)
            body.append('<%s><rdf:Alt>%s</rdf:Alt></%s>' % (prop, inner, prop))
        elif form in ('bag', 'seq'):
            inner = ''.join('<rdf:li>%s</rdf:li>' % escape(item, prop) for item in value)
            body.append('<%s><rdf:%s>%s</rdf:%s></%s>' % (prop, form.capitalize(), inner, form.capitalize(), prop))
        else:
            body.append('<%s>%s</%s>' % (prop, escape(value_text(form, value, prop), prop), prop))
    declared = ''.join('\n   xmlns:%s="%s"' % (p, u) for p, u in NAMESPACES if p in used)
    text = HEADER + '<rdf:Description rdf:about=""' + declared + '>\n' + ''.join('  ' + line + '\n' for line in body) + '</rdf:Description>\n' + FOOTER
    data = text.encode('utf-8')
    if len(data) > MAX_BYTES:
        raise SidecarError('SIDECAR_BOUND', 'the sidecar would exceed %d bytes' % MAX_BYTES, bytes=len(data))
    return data


def expected(model):
    """``{property: [occurrence]}`` that the hardened reader (``xmp.parse``) must return for ``build(model)`` (the structure it documents, built independently of the emitter)."""
    out = {}
    for key, prop, form, _ in ROWS:
        if key not in model:
            continue
        value = model[key]
        if form == 'alt':
            langs = {'x-default': value['text']}
            langs.update({e['language']: e['text'] for e in value.get('languages', [])})
            out[prop] = [{'kind': 'langAlt', 'value': langs}]
        elif form in ('bag', 'seq'):
            out[prop] = [{'kind': 'list', 'container': form.capitalize(), 'value': list(value)}]
        else:
            out[prop] = [{'kind': 'text', 'value': value_text(form, value, prop)}]
    return out


def keys_of(model):
    """The exact native listing keys the produced properties must have (a set)."""
    return {NATIVE[prop] for key, prop, _, _ in ROWS if key in model}
