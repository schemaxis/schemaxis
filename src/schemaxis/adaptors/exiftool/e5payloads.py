"""Shared raw-payload decoders for the E5 containers (standard library only).

Container locators hand out raw payload bytes; the existing hardened readers decode them (``tiff.walk``, ``xmp.parse``, ``iptc``). This
module adds only what several containers need around those readers: a bounded inflate for compressed XMP text, the Photoshop 3.0 wrapper
that lets TIFF and PNG IPTC reach the same ``iptc.resources`` reader as a JPEG APP13 body, and the legacy ``Raw profile type`` text form.
"""
import struct
import zlib

from schemaxis.adaptors.exiftool import iptc, tiff, xmp

PHOTOSHOP = b'Photoshop 3.0\0'
EXIF_PREFIX = b'Exif\0\0'
XMP_PREFIX = b'http://ns.adobe.com/xap/1.0/\0'
IPTC_RESOURCE = 0x0404
RAW_PROFILE = b'Raw profile type '
MAX_PROFILE_TEXT = 2 * xmp.MAX_BYTES + 4096


class Problem(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code, self.message = code, message


def inflate_bounded(data, limit):
    """Decompress one zlib stream to at most ``limit`` bytes; ``XMP_BOUND`` beyond it, ``XMP_MALFORMED`` for a damaged or unfinished stream."""
    stream = zlib.decompressobj()
    try:
        out = stream.decompress(bytes(data), limit + 1)
    except zlib.error as error:
        raise Problem('XMP_MALFORMED', 'a compressed text chunk is not a valid zlib stream: %s' % str(error)[:80])
    if len(out) > limit or stream.unconsumed_tail:
        raise Problem('XMP_BOUND', 'a compressed text chunk inflates past %d bytes' % limit)
    if not stream.eof:
        raise Problem('XMP_MALFORMED', 'a compressed text chunk is truncated')
    return out


def tiff_stream_ok(payload):
    """True when the payload starts with a classic TIFF byte-order header that the shared walker accepts."""
    try:
        tiff.header(payload)
    except tiff.Damaged:
        return False
    return True


def iim_walk_clean(iim):
    """Whether the bytes are exactly a sequence of well-formed IIM datasets (marker 0x1C, record, number, 16-bit length)."""
    position = 0
    while position < len(iim):
        if iim[position] != 0x1C or position + 5 > len(iim):
            return False
        length = struct.unpack_from('>H', iim, position + 3)[0]
        if length & 0x8000 or position + 5 + length > len(iim):
            return False
        position += 5 + length
    return True


def trim_iim_padding(iim):
    """Native 13.55 stores IIM in TIFF tag 0x83BB as a LONG array, so the datasets are followed by up to 3 zero pad bytes; those are dropped only when the rest is exactly well-formed."""
    iim = bytes(iim)
    if iim_walk_clean(iim):
        return iim
    for cut in (1, 2, 3):
        if len(iim) > cut and iim[-cut:] == b'\0' * cut and iim_walk_clean(iim[:-cut]):
            return iim[:-cut]
    return iim


def photoshop_body_from_iim(iim):
    """A Photoshop 3.0 resource body that wraps bare IPTC-IIM bytes (TIFF tag 0x83BB) so ``iptc.resources`` reads it like a JPEG APP13."""
    iim = trim_iim_padding(iim)
    return PHOTOSHOP + b'8BIM' + struct.pack('>H', IPTC_RESOURCE) + b'\0\0' + struct.pack('>I', len(iim)) + bytes(iim) + (b'\0' if len(iim) % 2 else b'')


def photoshop_body_from_resources(blocks):
    """The Photoshop 3.0 prefix in front of bare image-resource blocks (TIFF tag 0x8649)."""
    return PHOTOSHOP + bytes(blocks)


def psir_walk(blocks):
    """The image-resource blocks of bare ``8BIM`` data (a TIFF tag 0x8649 value, or a Photoshop 3.0 body without its prefix) as ``([(ident, name, data)], tail)``.

    The walk stops exactly where ``iptc.resources`` stops: a remainder shorter than 12 bytes is not a resource. That remainder is the ``tail`` and it is returned, never ignored: native
    13.55 rewrites a Photoshop block without it when IPTC changes (mailbox 7, observed), so a writer must know it exists. ``None`` is returned for malformed data."""
    blocks = bytes(blocks)
    position, found = 0, []
    while position + 12 <= len(blocks):
        if blocks[position:position + 4] != b'8BIM':
            return None
        ident = struct.unpack_from('>H', blocks, position + 4)[0]
        name_length = blocks[position + 6]
        name = blocks[position + 7:position + 7 + name_length]
        position += 6 + 1 + name_length + (1 + name_length) % 2
        if position + 4 > len(blocks):
            return None
        size = struct.unpack_from('>I', blocks, position)[0]
        position += 4
        if position + size > len(blocks):
            return None
        found.append((ident, name, blocks[position:position + size]))
        position += size + size % 2
    return found, blocks[min(position, len(blocks)):]


def psir_tail(body):
    """The opaque remainder after the last image resource of a Photoshop 3.0 body (a JPEG APP13 payload), or ``None`` when the body is not parseable."""
    if bytes(body[:len(PHOTOSHOP)]) != PHOTOSHOP:
        return None
    walked = psir_walk(bytes(body[len(PHOTOSHOP):]))
    return None if walked is None else walked[1]


def has_iptc_resource(body):
    """True when a Photoshop body holds an IPTC-NAA (0x0404) resource; ``None`` when the body cannot be parsed."""
    try:
        return any(ident == IPTC_RESOURCE for ident, _ in iptc.resources(body))
    except iptc.Problem:
        return None


def raw_profile(text):
    """Decode ImageMagick-style ``\\nname\\n   length\\nhex...`` text into ``(name, payload)``; ``None`` when it is not that form or is inconsistent."""
    lines = bytes(text).split(b'\n')
    if len(lines) < 4 or lines[0] != b'':
        return None
    try:
        name, length = lines[1].decode('ascii'), int(lines[2].strip())
        payload = bytes.fromhex(b''.join(lines[3:]).replace(b' ', b'').decode('ascii'))
    except ValueError:
        return None
    return (name, payload) if len(payload) == length else None


def decode(found):
    """Run the shared readers over every payload of a locator result: ``{'exif': [...], 'xmp': [...], 'iptc': [...]}``.

    Each list element is ``('ok', value)`` or ``('error', code, message)``; the walker, the XMP reader and the IPTC reader are the existing ones.
    """
    out = {'exif': [], 'xmp': [], 'iptc': []}
    for payload in found['exif']:
        try:
            out['exif'].append(('ok', tiff.walk(payload)))
        except tiff.Damaged as error:
            out['exif'].append(('error', error.code, error.message))
    for payload in found['xmp']:
        try:
            out['xmp'].append(('ok', xmp.parse(payload)))
        except xmp.Problem as error:
            out['xmp'].append(('error', error.code, error.message))
    for body in found['iptc']:
        try:
            blocks = [data for ident, data in iptc.resources(body) if ident == IPTC_RESOURCE]
            out['iptc'].append(('ok', [iptc.datasets(block) for block in blocks]))
        except iptc.Problem as error:
            out['iptc'].append(('error', error.code, error.message))
    return out
