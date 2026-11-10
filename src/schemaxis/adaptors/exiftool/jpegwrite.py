"""Strict JPEG structure walker and encoded-image preservation proofs for the metadata write family (standard library only).

``walk`` admits only files whose byte layout lets a metadata rewrite be proved harmless: SOI, header segments, one frame (baseline, extended
sequential or progressive Huffman), then scans that are separated only by DHT/DQT/DRI/SOS segments, EOI and no trailing byte. Entropy-coded
data is never decoded; ``FF00`` stuffing, restart markers (which must cycle modulo 8 from RST0 in every scan) and ``FF`` fill bytes are skipped
as data and can therefore never be mistaken for a segment. Everything the walker refuses is refused with a code, because a byte-for-byte tail
claim would otherwise rest on a layout the writer treats specially (trailers, segments after the first scan, multi-picture offsets).

``preservation`` states what a rewrite did to the encoded image: the bytes from the first scan header to the end, the frame header and the
coding tables before it, the rendering segments (JFIF, Adobe, ICC) and every other non-metadata segment are compared byte for byte, and the
editable metadata segments (Exif, standard XMP, Photoshop IRB) may differ only as declared. This is a statement about bytes, never about
pixels: no decoder is run, and it says nothing about image authenticity or provenance.
"""
import hashlib
import struct

MAX_SEGMENTS = 4096
MAX_SCANS = 1024
FRAMES = {0xC0: 'baseline', 0xC1: 'extended-sequential', 0xC2: 'progressive'}
UNSUPPORTED_FRAMES = {0xC3: 'lossless', 0xC5: 'differential-sequential', 0xC6: 'differential-progressive', 0xC7: 'differential-lossless', 0xC9: 'arithmetic-sequential',
                      0xCA: 'arithmetic-progressive', 0xCB: 'arithmetic-lossless', 0xCD: 'arithmetic-differential-sequential', 0xCE: 'arithmetic-differential-progressive',
                      0xCF: 'arithmetic-differential-lossless'}
TABLES = (0xC4, 0xDB, 0xDD, 0xCC)       # DHT, DQT, DRI, DAC: kept in order with the frame header as the coding description
BETWEEN_SCANS = (0xC4, 0xDB, 0xDD)
EXIF, XMP, XMP_EXTENDED, PHOTOSHOP = b'Exif\0\0', b'http://ns.adobe.com/xap/1.0/\0', b'http://ns.adobe.com/xmp/extension/\0', b'Photoshop 3.0\0'
ICC, JFIF, JFXX, ADOBE, MPF, FLASHPIX = b'ICC_PROFILE\0', b'JFIF\0', b'JFXX\0', b'Adobe', b'MPF\0', b'FPXR\0'


class Refused(Exception):
    def __init__(self, code, message, **observed):
        super().__init__(message)
        self.code, self.message, self.observed = code, message, observed


def sha(data): return hashlib.sha256(data).hexdigest()


def classify(marker, body):
    """The role of one pre-scan segment: the editable metadata segments, rendering segments, coding description or other."""
    if marker == 0xE1 and body.startswith(EXIF): return 'exif'
    if marker == 0xE1 and body.startswith(XMP): return 'xmp'
    if marker == 0xE1 and body.startswith(XMP_EXTENDED): return 'xmpExtended'
    if marker == 0xED and body.startswith(PHOTOSHOP): return 'iptc'
    if marker == 0xE0 and (body.startswith(JFIF) or body.startswith(JFXX)): return 'rendering'
    if marker == 0xEE and body.startswith(ADOBE): return 'rendering'
    if marker == 0xE2 and body.startswith(ICC): return 'rendering'
    if marker == 0xE2 and body.startswith(MPF): return 'mpf'
    if marker == 0xE2 and body.startswith(FLASHPIX): return 'flashpix'
    if marker in (0xC0, 0xC1, 0xC2) or marker in TABLES: return 'coding'
    return 'other'


def entropy(data, position, at):
    """Offset of the first real marker after the entropy-coded data that starts at ``position`` (``at`` is the scan header offset for messages)."""
    expected = 0
    while True:
        index = data.find(b'\xff', position)
        if index < 0 or index + 1 >= len(data):
            raise Refused('JPEG_TRUNCATED', 'the scan data ends without a following marker', offset=at)
        following = data[index + 1]
        if following == 0xFF:
            position = index + 1
        elif following == 0x00:
            position = index + 2
        elif 0xD0 <= following <= 0xD7:
            if following - 0xD0 != expected:
                raise Refused('JPEG_RESTART_SEQUENCE_INVALID', 'restart markers must cycle modulo 8 starting at RST0 in every scan', offset=index, found=following - 0xD0, expected=expected)
            expected = (expected + 1) % 8
            position = index + 2
        else:
            return index


def walk(data):
    """The strict structure of one admitted JPEG; raises ``Refused`` with a stable code."""
    if data[:2] != b'\xff\xd8':
        raise Refused('JPEG_SIGNATURE', 'the file does not start with a JPEG start-of-image marker')
    position, pre, frame, count = 2, [], None, 0
    while True:
        while position + 1 < len(data) and data[position] == 0xFF and data[position + 1] == 0xFF:
            position += 1
        if position + 2 > len(data) or data[position] != 0xFF:
            raise Refused('JPEG_TRUNCATED', 'the marker structure is truncated or malformed', offset=position)
        marker = data[position + 1]
        if marker == 0xDA:
            break
        if marker == 0xD9 or marker == 0x00 or marker == 0x01 or 0xD0 <= marker <= 0xD8:
            raise Refused('JPEG_STRUCTURE', 'a standalone marker appears before the first scan', marker=marker, offset=position)
        if position + 4 > len(data):
            raise Refused('JPEG_TRUNCATED', 'a segment header is truncated', offset=position)
        length = struct.unpack_from('>H', data, position + 2)[0]
        count += 1
        if count > MAX_SEGMENTS or length < 2 or position + 2 + length > len(data):
            raise Refused('JPEG_STRUCTURE', 'a segment length is invalid, truncated or exceeds the segment budget', marker=marker, offset=position)
        body = data[position + 4:position + 2 + length]
        if marker in UNSUPPORTED_FRAMES:
            raise Refused('UNSUPPORTED_JPEG_PROCESS', 'only Huffman baseline, extended sequential and progressive frames are admitted for writing', process=UNSUPPORTED_FRAMES[marker])
        if marker in (0xDC, 0xDE, 0xDF):
            raise Refused('UNSUPPORTED_JPEG_PROCESS', 'DNL, DHP and EXP segments are not admitted for writing', marker=marker)
        role = classify(marker, body)
        if marker in FRAMES:
            if frame is not None:
                raise Refused('UNSUPPORTED_JPEG_PROCESS', 'more than one frame header is not admitted for writing')
            if len(body) < 6 or struct.unpack_from('>HH', body, 1)[0] == 0:
                raise Refused('JPEG_STRUCTURE', 'the frame header is truncated or declares a zero height', offset=position)
            frame = {'process': FRAMES[marker], 'precision': body[0], 'height': struct.unpack_from('>H', body, 1)[0], 'width': struct.unpack_from('>H', body, 3)[0], 'components': body[5]}
        pre.append({'marker': marker, 'offset': position, 'length': length, 'role': role, 'sha256': sha(body), 'body': body})
        position += 2 + length
    if frame is None:
        raise Refused('JPEG_STRUCTURE', 'the file has no frame header before its first scan')
    roles = [s['role'] for s in pre]
    for role, code, message in (('xmpExtended', 'XMP_EXTENDED_UNSUPPORTED', 'extended XMP is not admitted for writing'), ('mpf', 'JPEG_MPF_UNSUPPORTED', 'a multi-picture (MPF) segment records offsets after the image and is not admitted for writing'),
                                ('flashpix', 'WRITE_UNSUPPORTED_SEGMENT', 'a FlashPix segment is not admitted for writing')):
        if role in roles:
            raise Refused(code, message)
    for role, label in (('exif', 'Exif'), ('xmp', 'XMP'), ('iptc', 'Photoshop')):
        if roles.count(role) > 1:
            raise Refused(role.upper() + '_SEGMENT_REPEATED', 'the file carries more than one %s segment, so no single one is authoritative' % label)
    first_scan, scans, tail = position, 0, []
    while True:
        if data[position + 1] != 0xDA:
            raise Refused('JPEG_STRUCTURE', 'a scan header was expected', offset=position)
        if position + 4 > len(data):
            raise Refused('JPEG_TRUNCATED', 'a scan header is truncated', offset=position)
        length = struct.unpack_from('>H', data, position + 2)[0]
        if length < 6 or position + 2 + length > len(data):
            raise Refused('JPEG_STRUCTURE', 'a scan header length is invalid', offset=position)
        scans += 1
        if scans > MAX_SCANS:
            raise Refused('JPEG_STRUCTURE', 'the file exceeds the scan budget of %d' % MAX_SCANS)
        position = entropy(data, position + 2 + length, position)
        while True:
            marker = data[position + 1]
            if marker == 0xD9:
                end = position + 2
                if end != len(data):
                    raise Refused('WRITE_TRAILER_UNSUPPORTED', 'bytes follow the end-of-image marker, which is not admitted for writing', trailing=len(data) - end)
                return {'frame': frame, 'pre': pre, 'firstScan': first_scan, 'scans': scans, 'tail': tail, 'end': end}
            if marker == 0xDA:
                break
            if marker not in BETWEEN_SCANS:
                raise Refused('WRITE_TAIL_SEGMENT_UNSUPPORTED', 'only DHT, DQT, DRI and SOS segments are admitted between scans', marker=marker, offset=position)
            if position + 4 > len(data):
                raise Refused('JPEG_TRUNCATED', 'a segment header is truncated', offset=position)
            length = struct.unpack_from('>H', data, position + 2)[0]
            if length < 2 or position + 2 + length > len(data):
                raise Refused('JPEG_STRUCTURE', 'a segment length is invalid or truncated', marker=marker, offset=position)
            tail.append({'marker': marker, 'offset': position, 'length': length})
            position += 2 + length
            while position + 1 < len(data) and data[position] == 0xFF and data[position + 1] == 0xFF:
                position += 1
            if position + 2 > len(data) or data[position] != 0xFF:
                raise Refused('JPEG_TRUNCATED', 'the marker structure after a scan is truncated', offset=position)


def segments_of(structure, *roles):
    return [s for s in structure['pre'] if s['role'] in roles]


def coding(structure):
    return [(s['marker'], s['sha256']) for s in structure['pre'] if s['role'] == 'coding']


def preservation(before, after, captured, written, declared):
    """Byte-level preservation findings of one rewrite: a list of ``{code, message, ...}`` (empty means every claim holds).

    ``captured`` and ``written`` are the whole file bytes, ``before`` and ``after`` their walks. ``declared`` names what the plan may have
    changed: ``exif``, ``xmp``, ``iptc`` (segments that may differ), ``comment`` (COM segments may be removed) and ``thumbnail`` (IFD1 may go).
    """
    problems = []
    tail_in, tail_out = captured[before['firstScan']:], written[after['firstScan']:]
    if tail_in != tail_out:
        problems.append({'code': 'IMAGE_DATA_CHANGED', 'message': 'the bytes from the first scan header to the end differ from the capture',
                         'captureSha256': sha(tail_in), 'outputSha256': sha(tail_out), 'captureBytes': len(tail_in), 'outputBytes': len(tail_out)})
    if coding(before) != coding(after):
        problems.append({'code': 'IMAGE_DATA_CHANGED', 'message': 'the frame header or the coding tables before the first scan differ from the capture'})
    if [(s['marker'], s['body']) for s in segments_of(before, 'rendering')] != [(s['marker'], s['body']) for s in segments_of(after, 'rendering')]:
        problems.append({'code': 'RENDERING_SEGMENT_CHANGED', 'message': 'a JFIF, Adobe or ICC profile segment differs from the capture, or was added, removed or reordered'})
    other_in = [(s['marker'], s['body']) for s in segments_of(before, 'other') if not (s['marker'] == 0xFE and 'comment' in declared)]
    if other_in != [(s['marker'], s['body']) for s in segments_of(after, 'other')]:
        problems.append({'code': 'SEGMENT_CHANGED', 'message': 'a segment outside the editable metadata (a COM or other application segment) differs from the capture, or was added, removed or reordered'})
    for role in ('exif', 'xmp', 'iptc'):
        a, b = segments_of(before, role), segments_of(after, role)
        if role not in declared and [s['body'] for s in a] != [s['body'] for s in b]:
            problems.append({'code': 'UNDECLARED_SEGMENT_CHANGE', 'message': 'the %s segment changed although no destination of the plan writes it' % role})
        if role == 'exif' and not a and b and 'exifCreate' not in declared:
            problems.append({'code': 'UNDECLARED_SEGMENT_CHANGE', 'message': 'an Exif segment appeared; metadata edits never create one'})
    return problems
