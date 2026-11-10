"""Container locators: find the metadata payloads and facts of a media file without decoding pixels (standard library only).

A locator returns payload bytes by family (``exif``, ``xmp``, ``iptc``) and container facts; shared payload decoders interpret them. It
refuses only what it cannot locate safely (not this container, truncated marker structure, budget). Anything it does not interpret
(extended XMP, MakerNotes, trailers, ICC) is reported as a note, never silently dropped. JPEG entropy data is scanned for markers only.
"""
import struct

MAX_BYTES = 64 * 1024 * 1024
MAX_SEGMENTS = 4096
SOF = {0xC0: 'baseline', 0xC1: 'extended-sequential', 0xC2: 'progressive', 0xC3: 'lossless', 0xC5: 'differential-sequential',
       0xC6: 'differential-progressive', 0xC7: 'differential-lossless', 0xC9: 'arithmetic-sequential', 0xCA: 'arithmetic-progressive',
       0xCB: 'arithmetic-lossless', 0xCD: 'arithmetic-differential-sequential', 0xCE: 'arithmetic-differential-progressive',
       0xCF: 'arithmetic-differential-lossless'}
CAPABILITIES = {'jpeg': ('exif', 'xmp', 'iptc', 'container'), 'xmp': ('xmp',),
                'tiff': ('exif', 'xmp', 'iptc', 'container'), 'dng': ('exif', 'xmp', 'iptc', 'container'),
                'png': ('exif', 'xmp', 'container'), 'webp': ('exif', 'xmp', 'container'), 'heif': ('exif', 'xmp', 'container')}   # E5: equals the destinations of containerprofiles.json (a test pins it)
EXIF_PREFIX = b'Exif\0\0'
XMP_PREFIX = b'http://ns.adobe.com/xap/1.0/\0'
XMP_EXTENDED = b'http://ns.adobe.com/xmp/extension/\0'
PHOTOSHOP = b'Photoshop 3.0\0'
ICC = b'ICC_PROFILE\0'


class Refused(Exception):
    def __init__(self, code, message, **observed):
        super().__init__(message)
        self.code, self.message, self.observed = code, message, observed


def kind_of(data):
    if data[:2] == b'\xff\xd8':
        return 'jpeg'
    head = data[:4096].lstrip(b'\xef\xbb\xbf \t\r\n')
    if head[:5] == b'<?xml' or head[:7] == b'<?xpack' or head[:10] == b'<x:xmpmeta' or head[:9] == b'<rdf:RDF':
        return 'xmp'
    return None


def locate(data):
    """Locate payloads of one file: ``{'container': 'jpeg'|'xmp', 'exif': [...], 'xmp': [...], 'iptc': [...], 'frame': {...}, 'notes': [...]}``."""
    if len(data) > MAX_BYTES:
        raise Refused('PHOTO_RESOURCE_LIMIT', 'the file exceeds %d bytes' % MAX_BYTES, bytes=len(data))
    kind = kind_of(data)
    if kind == 'xmp':
        return {'container': 'xmp', 'exif': [], 'xmp': [data], 'iptc': [], 'frame': None, 'notes': []}
    if kind != 'jpeg':
        raise Refused('UNSUPPORTED_MEDIA', 'the file is neither a JPEG nor an XMP sidecar (other containers are not located yet)')
    return jpeg(data)


def jpeg(data):
    position, count = 2, 0
    found = {'container': 'jpeg', 'exif': [], 'xmp': [], 'iptc': [], 'frame': None, 'notes': []}
    extended = icc = scans = 0
    while True:
        while position + 1 < len(data) and data[position] == 0xFF and data[position + 1] == 0xFF:
            position += 1
        if position + 2 > len(data) or data[position] != 0xFF:
            raise Refused('INVALID_PHOTO_DATA', 'JPEG marker structure is truncated or malformed', offset=position)
        marker = data[position + 1]
        if marker == 0xD9:
            break
        if marker == 0x00 or marker == 0x01 or 0xD0 <= marker <= 0xD8:
            position += 2
            continue
        if position + 4 > len(data):
            raise Refused('INVALID_PHOTO_DATA', 'JPEG marker structure is truncated or malformed', offset=position)
        length = struct.unpack_from('>H', data, position + 2)[0]
        count += 1
        if count > MAX_SEGMENTS or length < 2 or position + 2 + length > len(data):
            raise Refused('INVALID_PHOTO_DATA', 'a JPEG segment length is invalid, truncated or exceeds the segment budget', marker=marker)
        body = data[position + 4:position + 2 + length]
        position += 2 + length
        if marker in SOF:
            if found['frame'] is not None:
                found['notes'].append('multiple-frames')
            elif len(body) < 6:
                raise Refused('INVALID_PHOTO_DATA', 'a JPEG frame header is truncated')
            else:
                height, width = struct.unpack_from('>HH', body, 1)
                found['frame'] = {'width': width, 'height': height, 'process': SOF[marker], 'precision': body[0], 'components': body[5]}
        elif marker == 0xE1 and body[:6] == EXIF_PREFIX:
            found['exif'].append(body[6:])
        elif marker == 0xE1 and body[:len(XMP_PREFIX)] == XMP_PREFIX:
            found['xmp'].append(body[len(XMP_PREFIX):])
        elif marker == 0xE1 and body[:len(XMP_EXTENDED)] == XMP_EXTENDED:
            extended += 1
        elif marker == 0xED and body[:len(PHOTOSHOP)] == PHOTOSHOP:
            found['iptc'].append(body)
        elif marker == 0xE2 and body[:len(ICC)] == ICC:
            icc += 1
        elif marker == 0xDA:
            scans += 1
            position = skip_entropy(data, position)
            if position is None:
                raise Refused('INVALID_PHOTO_DATA', 'JPEG is truncated: no final EOI after the scan data')
    if found['frame'] is None:
        raise Refused('INVALID_PHOTO_DATA', 'the JPEG has no frame header')
    if extended:
        found['notes'].append('extended-xmp-not-read')
    if icc:
        found['notes'].append('icc-profile-present-not-decoded')
    if position + 2 < len(data):
        found['notes'].append('bytes-after-eoi:%d' % (len(data) - position - 2))
    found['scans'] = scans
    return found


def skip_entropy(data, position):
    """Index of the next real marker after entropy-coded data (stuffed bytes and restarts skipped), or None."""
    while True:
        index = data.find(b'\xff', position)
        if index < 0 or index + 1 >= len(data):
            return None
        following = data[index + 1]
        if following == 0 or 0xD0 <= following <= 0xD7 or following == 0xFF:
            position = index + (1 if following == 0xFF else 2)
            continue
        return index
