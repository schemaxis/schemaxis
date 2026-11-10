"""Bounded WebP publication of one captured PNG, verified by fresh native decoding, and the reverse decode to PNG.

Three operations share one route. ``encodeLossless`` (below) proves every RGBA sample identical.
``encodeLossy`` is an explicit opaque-only branch: ``cwebp -q N -m 6`` with an authored integer quality, then
a trusted fresh ``dwebp`` decode whose every RGB sample the host compares with the source. The published file is
accepted only inside an authored mean-absolute-RGB-error budget and byte budget; there is no perceptual claim.
``decodeToPng`` is the explicit reverse handoff: one captured static simple-format WebP (one VP8L chunk, or one
opaque VP8 chunk) is decoded by the trusted ``dwebp -nodither -pam`` and written as a canonical PNG (only IHDR, IDAT and
IEND). It needs only ``dwebp``; a fresh ``dwebp`` decode of the captured bytes must equal every sample of the published PNG.

The host decodes the captured PNG with the shared bounded decoder and writes a canonical PAM
bridge (the libwebp source build has no libpng). ``cwebp -lossless -exact`` encodes it, and
``dwebp -pam`` decodes the published bytes in a separate process. A strict host PAM reader and
RIFF/VP8L framing check compare every RGBA byte with the captured PNG. There is no independent
host WebP decoder: verification therefore needs the trusted, separately configured ``dwebp``.
Receipts never supply an executable.
"""
from fractions import Fraction
import hashlib
import json
import math
import operator
import os
from pathlib import Path
import re
import stat
import struct
import sys
import tempfile
import zlib

from schemaxis import png
from schemaxis.artifacts import atomic_json
from schemaxis.configuration import executable as configured_executable, locations as configured_locations
from schemaxis.core.declarations import validate_arguments
from schemaxis.core.faults import Fault, SchemaxisError
from schemaxis.dispatch import execution_deadline, remaining_timeout
from schemaxis.errors import fail, keys
from schemaxis.native_command import execute

VERSION = 'schemaxis.webp/1'
OPERATION = 'encodeLossless'
LOSSY = 'encodeLossy'
DECODE = 'decodeToPng'
PLAN_VERSION = 'schemaxis.webp.plan/1'
SUMMARY_VERSION = 'schemaxis.webp.summary/1'
MAX_SIDE = 2048
MAX_PIXELS = 1048576
MAX_SOURCE_BYTES = 8 * 1024 * 1024
MAX_WEBP_BYTES = 16 * 1024 * 1024
MAX_LOG_BYTES = 1024 * 1024
MAX_PNG_BYTES = 5 * MAX_PIXELS
STAGE_TIMEOUT = 120
VERIFY_TIMEOUT = 120
ENCODE_ARGUMENTS = ['-lossless', '-exact', '-z', '6']
LOSSY_FIXED = ['-m', '6', '-alpha_q', '100']
DECODE_ARGUMENTS = ['-nodither', '-pam']
ENCODER_IDENTITY = re.compile(r'(1\.6\.\d+)\nlibsharpyuv: (\d+\.\d+\.\d+)\n?')
DECODER_IDENTITY = re.compile(r'(1\.6\.\d+)\n?')
PAM_HEADER = re.compile(rb'P7\nWIDTH ([1-9][0-9]*)\nHEIGHT ([1-9][0-9]*)\nDEPTH 4\nMAXVAL 255\nTUPLTYPE RGB_ALPHA\nENDHDR\n')
SRGB_CHROMATICITIES = struct.pack('>8I', 31270, 32900, 64000, 33000, 30000, 60000, 15000, 6000)
SRGB_GAMMA = struct.pack('>I', 45455)
PNG_SIGNATURE = b'\x89PNG\r\n\x1a\n'
NATIVE_REPORT = re.compile(r'Decoded captured\.webp\. Dimensions: ([1-9][0-9]*) x ([1-9][0-9]*) ( \(with alpha\))?\. Format: (lossless|lossy)\. Now saving\.\.\.\nSaved file decoded\.pam\n?')
COLOUR_REJECTED = (b'iCCP', b'cICP')
ANIMATION_CHUNKS = (b'acTL', b'fcTL', b'fdAT')

OPTIONS = {'source': {'type': 'string', 'minLength': 1, 'maxLength': 4096, 'required': True}}
LOSSY_OPTIONS = {**OPTIONS,
                 'quality': {'type': 'integer', 'minimum': 0, 'maximum': 100, 'required': True},
                 'maxMeanRGBError': {'type': 'number', 'minimum': 0, 'maximum': 255, 'required': True},
                 'maxBytes': {'type': 'integer', 'minimum': 1, 'maximum': MAX_WEBP_BYTES}}
DECLARATIONS = {OPERATION: {
    'native': 'cwebp -lossless -exact -z 6 INPUT.pam -o image.webp; dwebp image.webp -pam -o reopened.pam (libwebp 1.6; VP8L)',
    'kinds': ['image', 'text'], 'inputs': {}, 'options': {k: {'value': v} for k, v in OPTIONS.items()}},
    LOSSY: {
    'native': 'cwebp -q QUALITY -m 6 -alpha_q 100 INPUT.pam -o image.webp; dwebp image.webp -pam -o reopened.pam (libwebp 1.6; opaque VP8)',
    'kinds': ['image', 'text'], 'inputs': {}, 'options': {k: {'value': v} for k, v in LOSSY_OPTIONS.items()}},
    DECODE: {
    'native': 'dwebp captured.webp -nodither -pam -o decoded.pam (libwebp 1.6; one simple VP8L or opaque VP8 chunk); the host writes the canonical PNG',
    'kinds': ['image', 'text'], 'inputs': {}, 'options': {k: {'value': v} for k, v in OPTIONS.items()}}}
LOSSES = [
    'Input is one non-interlaced 8-bit RGB or RGBA PNG, at most 2048 pixels per side and 1,048,576 pixels, 8 MiB; palette, greyscale, 16-bit, interlaced, tRNS and animated PNGs are refused.',
    'Pixels are exact: every RGBA sample, including RGB beneath zero alpha (cwebp -exact), is read back from the published bytes. RGB sources gain alpha 255.',
    'The PNG is treated as sRGB when untagged or tagged sRGB/gAMA 45455/cHRM sRGB; ICC profiles (iCCP), cICP and any other gAMA/cHRM are refused. The WebP carries no colour profile, so decoders assume sRGB.',
    'All ancillary PNG chunks (text, EXIF, physical size, timestamps, background) are dropped and listed in the summary; the WebP has no EXIF, XMP or ICC chunk.',
    'Lossless encoding with fixed effort (-z 6) only: no lossy, near-lossless, resize, crop, animation, metadata retention or authored native flags. Output size depends on content and is not guaranteed smaller than the PNG.',
    'Verification re-decodes the actual published bytes with a separately configured native dwebp; no independent host WebP decoder exists.']
LOSSY_LOSSES = [
    'Input is one non-interlaced 8-bit RGB or RGBA PNG within the same limits as encodeLossless, and every pixel must have alpha 255. Partial or zero alpha is refused with WEBP_ALPHA_UNSUPPORTED; use encodeLossless for transparency.',
    'Lossy: RGB samples change. The published WebP is accepted only if the mean absolute error over all width*height*3 R, G and B samples between the source and a fresh dwebp decode is at most maxMeanRGBError (0..255), and the file is at most maxBytes. The error is measured against the decode of the trusted dwebp with its default options; it is not a perceptual score and says nothing about other decoders or viewers.',
    'Quality is the authored integer for cwebp -q (0..100, a lossy quality setting; 100 is not lossless). There is no automatic quality search, no guarantee of any compression ratio, and the result may be larger than the PNG. A tight error budget (including 0) may legitimately refuse a run (DELIVERABLE_NOT_MET).',
    'Fixed effort -m 6 and -alpha_q 100; no near-lossless, resize, crop, animation, metadata or authored native flags. The WebP is one simple-format VP8 chunk with no alpha, ICC, EXIF or XMP.',
    'PNG colour rules and dropped ancillary chunks are those of encodeLossless; the WebP carries no colour profile, so decoders assume sRGB.']
DECODE_LOSSES = [
    'Input is one static simple-format WebP of at most 16 MiB: a RIFF file with exactly one VP8L chunk (lossless, with or without the alpha hint) or exactly one VP8 chunk (opaque lossy), at most 2048 pixels per side and 1,048,576 pixels. The extended format (VP8X: animation, ALPH alpha, ICC, EXIF, XMP), unknown or extra chunks, trailing bytes and inconsistent RIFF/chunk sizes are refused before any native process runs.',
    'The PNG holds exactly the samples that the trusted libwebp 1.6 dwebp decodes with its default options (-nodither, fancy upsampling): lossless input is exact, including RGB beneath zero alpha; lossy input is the decoder output, not the original picture, and another decoder may differ slightly.',
    'The PNG is 8-bit RGB when the WebP has no alpha hint and RGBA when the VP8L alpha hint is set. A WebP whose hint says opaque but whose decoded alpha is not 255 everywhere is refused with WEBP_ALPHA_MISMATCH when run, and fails verification with VERIFICATION_FAILED.',
    'The two upscaling bits of the VP8 width and height fields are a display hint: libwebp ignores them and decodes the coded size, and so does the adaptor, so the PNG has the coded dimensions whatever the bits say. The key-frame tag, start code, first-partition size, dimensions and budgets are still checked.',
    'Only IHDR, IDAT and IEND are written: no sRGB, gAMA, iCCP or text chunk, so the PNG is untagged and, by web convention, sRGB; WebP metadata does not exist in the accepted profile. The IDAT bytes are compressed by the host zlib (level 9, filter none), so the PNG file digest depends on the host zlib build while every sample does not.',
    'Verification re-decodes the captured WebP with a separately configured native dwebp and compares every RGBA sample with the published PNG, read by two independent host PNG readers. This is semantic agreement with libwebp, not an independent host WebP decoder, and does not authenticate where the WebP came from. Only dwebp is needed; cwebp is not.']


# ---------------------------------------------------------------- planning
def lossy_arguments(quality):
    return ['-q', str(quality), *LOSSY_FIXED]


def plan(document):
    lossy = isinstance(document, dict) and document.get('operation') == LOSSY
    decode = isinstance(document, dict) and document.get('operation') == DECODE
    options = LOSSY_OPTIONS if lossy else OPTIONS
    keys(document, ('version', 'operation', *options), '$')
    if document.get('version') != VERSION:
        fail('UNSUPPORTED_VERSION', 'expected ' + VERSION)
    if document.get('operation') not in (OPERATION, LOSSY, DECODE):
        fail('UNKNOWN_FILTER', 'select %s, %s or %s' % (OPERATION, LOSSY, DECODE), '$.operation')
    prepared = validate_arguments(options, {k: v for k, v in document.items() if k in options})
    source = prepared['source']
    suffix = '.webp' if decode else '.png'
    if '\0' in source or not Path(source).is_absolute() or Path(source).suffix.lower() != suffix:
        fail('INVALID_WEBP_SOURCE', 'select an absolute local regular %s file; no URLs, prefixes or relative paths' % suffix, '$.source')
    if decode:
        return {'version': PLAN_VERSION, 'operation': DECODE, **prepared,
                'decoding': {'format': 'WebP simple format (one VP8L chunk, or one opaque VP8 chunk) to PNG 8-bit RGB or RGBA with only IHDR, IDAT and IEND', 'arguments': DECODE_ARGUMENTS, 'metadata': 'none'},
                'budget': {'maxSide': MAX_SIDE, 'maxPixels': MAX_PIXELS, 'maxWebpBytes': MAX_WEBP_BYTES, 'maxPngBytes': MAX_PNG_BYTES},
                'losses': DECODE_LOSSES}
    if lossy:
        effective = prepared.get('maxBytes', MAX_WEBP_BYTES)
        return {'version': PLAN_VERSION, 'operation': LOSSY, **prepared,
                'encoding': {'format': 'WebP lossy (RIFF simple format, one opaque VP8 chunk)', 'arguments': lossy_arguments(prepared['quality']), 'metadata': 'none'},
                'budget': {'maxSide': MAX_SIDE, 'maxPixels': MAX_PIXELS, 'maxSourceBytes': MAX_SOURCE_BYTES, 'maxWebpBytes': MAX_WEBP_BYTES,
                           'maxBytes': effective, 'maxBytesSource': 'authored' if 'maxBytes' in prepared else 'default: the global %d-byte WebP cap' % MAX_WEBP_BYTES,
                           'maxMeanRGBError': prepared['maxMeanRGBError']},
                'losses': LOSSY_LOSSES}
    return {'version': PLAN_VERSION, 'operation': OPERATION, **prepared,
            'encoding': {'format': 'WebP lossless (RIFF simple format, VP8L)', 'arguments': ENCODE_ARGUMENTS, 'metadata': 'none'},
            'budget': {'maxSide': MAX_SIDE, 'maxPixels': MAX_PIXELS, 'maxSourceBytes': MAX_SOURCE_BYTES, 'maxWebpBytes': MAX_WEBP_BYTES},
            'losses': LOSSES}


def schema():
    from schemaxis.schema import DRAFT, argument_schema, object_schema
    lossless = object_schema({'version': {'const': VERSION}, 'operation': {'const': OPERATION},
                              **{k: argument_schema(v) for k, v in OPTIONS.items()}}, ['version', 'operation', 'source'])
    lossy = object_schema({'version': {'const': VERSION}, 'operation': {'const': LOSSY},
                           **{k: argument_schema(v) for k, v in LOSSY_OPTIONS.items()}},
                          ['version', 'operation', 'source', 'quality', 'maxMeanRGBError'])
    decode = object_schema({'version': {'const': VERSION}, 'operation': {'const': DECODE},
                            **{k: argument_schema(v) for k, v in OPTIONS.items()}}, ['version', 'operation', 'source'])
    properties = {**lossless['properties'], **lossy['properties'], 'operation': {'enum': [OPERATION, LOSSY, DECODE]}}
    return {'$schema': DRAFT, **object_schema(properties, ['version', 'operation']), 'oneOf': [lossless, lossy, decode]}


def query(document):
    return [plan(document)['operation']], {}


def resources(document, execution, identity):
    if execution.get('threads', 1) != 1:
        fail('INVALID_EXECUTION', 'WebP publication supports one serial thread', identity)
    return {'threads': 1}


# ---------------------------------------------------------------- bounded host inputs
def bounded(path, code='VERIFICATION_FAILED', limit=MAX_SOURCE_BYTES, location=None):
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0))
        with os.fdopen(fd, 'rb') as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size > limit:
                raise ValueError('not a bounded regular file')
            data = stream.read(limit + 1)
        if len(data) > limit:
            raise ValueError('byte budget exceeded')
        return data
    except (OSError, ValueError) as error:
        fail(code, 'select an intact regular file within %d bytes: %s' % (limit, error), location or str(path))


def sha(data):
    return hashlib.sha256(data).hexdigest()


def digest(directory, name, limit=MAX_WEBP_BYTES, held=None):
    """SHA-256 of a retained file; ``held`` maps names to bytes already read, so one snapshot binds every comparison."""
    if held and name in held:
        return sha(held[name])
    return sha(bounded(Path(directory) / name, limit=limit))


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate JSON key ' + key)
        result[key] = value
    return result


def finite_number(text):
    value = float(text)
    if not math.isfinite(value):
        raise ValueError('non-finite JSON number ' + text[:20])
    return value


def refuse_constant(name):
    raise ValueError('non-finite JSON constant ' + name)


def strict_json(data, name):
    """Strict UTF-8 JSON: no byte-order mark, duplicate keys, NaN/Infinity, numbers that overflow to infinity or excess depth."""
    try:
        text = data.decode('utf-8')
        if text.startswith('\ufeff'):
            raise ValueError('byte-order mark')
        return json.loads(text, object_pairs_hook=unique_object, parse_float=finite_number, parse_constant=refuse_constant)
    except (ValueError, UnicodeError, RecursionError) as error:
        fail('VERIFICATION_FAILED', 'invalid retained JSON %s: %s' % (name, str(error)[:80]))


def read_json(directory, name):
    return strict_json(bounded(Path(directory) / name, limit=MAX_LOG_BYTES), name)


def same_json(actual, expected):
    """Typed canonical comparison: 1 is not true and 66 is not 66.0, unlike Python equality."""
    try:
        return json.dumps(actual, sort_keys=True, allow_nan=False) == json.dumps(expected, sort_keys=True, allow_nan=False)
    except (ValueError, TypeError, RecursionError):
        return False


def declared_size(data, location):
    """Check PNG IHDR dimensions against the budget before any decompression."""
    if len(data) < 33 or data[:8] != b'\x89PNG\r\n\x1a\n' or data[12:16] != b'IHDR':
        fail('INVALID_WEBP_PNG', 'expected a complete bounded non-interlaced 8-bit RGB/RGBA PNG', location)
    width, height = struct.unpack_from('>II', data, 16)
    if not (0 < width <= MAX_SIDE and 0 < height <= MAX_SIDE and width * height <= MAX_PIXELS):
        fail('WEBP_PIXEL_BUDGET', 'PNG is %dx%d; at most %d pixels per side and %d pixels are supported' % (width, height, MAX_SIDE, MAX_PIXELS), location)
    return width, height


def admit_png(data, location='$.source'):
    """Decode the captured PNG with the shared decoder, then apply the colour/animation policy."""
    declared_size(data, location)
    try:
        width, height, rgba = png.decode(data)
    except SchemaxisError as error:
        fault = error.fault
        raise SchemaxisError(Fault('INVALID_WEBP_PNG', fault.message, location, fault.phase, fault.retryable, fault.observed,
                                   'select a complete non-interlaced 8-bit RGB/RGBA PNG without tRNS; re-export it deliberately')) from None
    chunks, offset = {}, 8
    while offset < len(data):
        length, kind = struct.unpack_from('>I4s', data, offset)
        chunks.setdefault(kind, data[offset + 8:offset + 8 + length])
        offset += length + 12
    if any(kind in chunks for kind in ANIMATION_CHUNKS):
        fail('WEBP_ANIMATION_UNSUPPORTED', 'animated PNG; export one static frame', location)
    if any(kind in chunks for kind in COLOUR_REJECTED):
        fail('WEBP_COLOUR_UNSUPPORTED', 'embedded colour profile or coding-independent code points cannot be carried; export an sRGB PNG', location)
    if chunks.get(b'gAMA', SRGB_GAMMA) != SRGB_GAMMA or chunks.get(b'cHRM', SRGB_CHROMATICITIES) != SRGB_CHROMATICITIES:
        fail('WEBP_COLOUR_UNSUPPORTED', 'gAMA/cHRM declare a colour space other than sRGB; convert to sRGB before publishing', location)
    declared = sorted(name.decode() for name in (b'sRGB', b'gAMA', b'cHRM') if name in chunks)
    dropped = sorted(kind.decode('latin-1') for kind in chunks if kind not in (b'IHDR', b'IDAT', b'IEND', b'sRGB', b'gAMA', b'cHRM'))
    return {'width': width, 'height': height, 'rgba': rgba,
            'colourDeclaration': '+'.join(declared) if declared else 'untagged (treated as sRGB)', 'droppedChunks': dropped}


def reusableInputs(document):
    prepared = plan(document)
    source = prepared['source']
    if prepared['operation'] == DECODE:
        data = bounded(source, 'INVALID_WEBP_SOURCE', MAX_WEBP_BYTES, '$.source')
        source_header(data, '$.source')
        return {source: sha(data)}
    data = bounded(source, 'INVALID_WEBP_SOURCE', location='$.source')
    declared_size(data, '$.source')
    return {source: sha(data)}


# ---------------------------------------------------------------- strict WebP and PAM readers
def pam(width, height, rgba):
    return b'P7\nWIDTH %d\nHEIGHT %d\nDEPTH 4\nMAXVAL 255\nTUPLTYPE RGB_ALPHA\nENDHDR\n' % (width, height) + rgba


def read_pam(data):
    """Strict canonical P7 RGB_ALPHA reader: exact header, bounded dimensions, exact payload length."""
    found = PAM_HEADER.match(data)
    if not found:
        fail('VERIFICATION_FAILED', 'native decode is not a canonical P7 RGB_ALPHA PAM')
    width, height = int(found.group(1)), int(found.group(2))
    if width > MAX_SIDE or height > MAX_SIDE or width * height > MAX_PIXELS:
        fail('VERIFICATION_FAILED', 'decoded PAM exceeds the pixel budget')
    pixels = data[found.end():]
    if len(pixels) != 4 * width * height:
        fail('VERIFICATION_FAILED', 'decoded PAM payload length differs from its dimensions')
    return width, height, pixels


def webp_header(data):
    """Strict RIFF/WebP framing: exactly one VP8L chunk. Returns dimensions and the alpha-used flag."""
    def refuse(message):
        fail('VERIFICATION_FAILED', 'published WebP is not a simple lossless file: ' + message)
    if len(data) < 25 or data[:4] != b'RIFF' or data[8:12] != b'WEBP':
        refuse('missing RIFF/WEBP header')
    if struct.unpack_from('<I', data, 4)[0] != len(data) - 8:
        refuse('RIFF size differs from the file length')
    kind, size = data[12:16], struct.unpack_from('<I', data, 16)[0]
    if kind != b'VP8L':
        refuse('chunk %r is not VP8L (lossy, extended, animated, ICC, EXIF and XMP files are unsupported)' % kind)
    if 20 + size + (size & 1) != len(data) or (size & 1 and data[-1] != 0) or size < 5:
        refuse('VP8L chunk framing differs from the file length (trailing or extra chunks)')
    if data[20] != 0x2f:
        refuse('VP8L signature byte differs')
    bits = struct.unpack_from('<I', data, 21)[0]
    if bits >> 29:
        refuse('unsupported VP8L version')
    width, height = (bits & 0x3fff) + 1, ((bits >> 14) & 0x3fff) + 1
    if width > MAX_SIDE or height > MAX_SIDE or width * height > MAX_PIXELS:
        refuse('dimensions exceed the pixel budget')
    return {'width': width, 'height': height, 'alphaFlag': bool((bits >> 28) & 1)}


def vp8_header(data):
    """Strict simple-format opaque lossy WebP: one ``VP8 `` chunk, keyframe tag, start code, unscaled dimensions.

    Only framing is judged here, before any native decode; the pixels are judged from a fresh dwebp decode and the
    byte budget by ``judge_bytes``.
    """
    def refuse(message):
        fail('VERIFICATION_FAILED', 'published WebP is not a simple opaque lossy file: ' + message)
    if len(data) < 30 or data[:4] != b'RIFF' or data[8:12] != b'WEBP':
        refuse('missing RIFF/WEBP header')
    if struct.unpack_from('<I', data, 4)[0] != len(data) - 8:
        refuse('RIFF size differs from the file length')
    kind, size = data[12:16], struct.unpack_from('<I', data, 16)[0]
    if kind != b'VP8 ':
        refuse('chunk %r is not VP8 (lossless, extended, alpha, animated, ICC, EXIF and XMP files are unsupported)' % kind)
    if 20 + size + (size & 1) != len(data) or (size & 1 and data[-1] != 0) or size < 10:
        refuse('VP8 chunk framing differs from the file length (trailing or extra chunks)')
    tag = data[20] | data[21] << 8 | data[22] << 16
    if tag & 1 or (tag >> 1) & 7 > 3 or not (tag >> 4) & 1:
        refuse('frame tag is not a displayed key frame of profile 0-3')
    if not 0 < tag >> 5 <= size - 10:
        refuse('first partition size does not fit the chunk')
    if data[23:26] != b'\x9d\x01\x2a':
        refuse('VP8 key frame start code differs')
    raw_width, raw_height = struct.unpack_from('<HH', data, 26)
    if raw_width >> 14 or raw_height >> 14:
        refuse('upscaling bits are set')
    width, height = raw_width & 0x3fff, raw_height & 0x3fff
    if not (0 < width <= MAX_SIDE and 0 < height <= MAX_SIDE and width * height <= MAX_PIXELS):
        refuse('dimensions exceed the pixel budget')
    return {'width': width, 'height': height, 'alphaFlag': False}


# ---------------------------------------------------------------- trusted runtimes
def runtime(encoder=None, decoder=None, need_encoder=True):
    """Trusted executables: explicit argument, then invocation context/stored configuration, then the environment.

    Receipts, evidence and authored input never supply an executable path.
    """
    wanted = [('encoder', encoder, lambda: configured_executable('webp'), 'SCHEMAXIS_WEBP', 'cwebp 1.6',
               'use --webp, schemaxis configure webp, or SCHEMAXIS_WEBP'),
              ('decoder', decoder, lambda: configured_locations().get('dwebp'), 'SCHEMAXIS_DWEBP', 'dwebp 1.6',
               'use --dwebp for run; for schemaxis verify use SCHEMAXIS_DWEBP or a stored locations.dwebp entry '
               'in the private configuration file (schemaxis configure only names adaptors)')]
    paths = {}
    for name, given, configured, variable, label, recovery in wanted:
        if name == 'encoder' and not need_encoder:
            continue
        value = given or configured() or os.environ.get(variable)
        if not isinstance(value, str) or not os.path.isabs(value) or not os.access(value, os.X_OK) or not os.path.isfile(value):
            fail('INTERPRETER_NOT_FOUND', 'configure an absolute %s executable%s' % (label, '; verification re-decodes the published bytes natively because no host WebP decoder exists' if name == 'decoder' else ''),
                 '$.runtime.' + name, recovery=recovery)
        paths[name] = value
    return paths


def launcher(stage, names, command):
    """Fixed trusted launcher: resource caps, bounded input binding, minimal environment, then exec."""
    return ('import hashlib,json,os,stat,resource\nfrom pathlib import Path\n'
            'resource.setrlimit(resource.RLIMIT_AS,(2147483648,2147483648))\n'
            'resource.setrlimit(resource.RLIMIT_FSIZE,(%d,%d))\n' % (MAX_WEBP_BYTES + 5 * MAX_PIXELS, MAX_WEBP_BYTES + 5 * MAX_PIXELS)
            + 'resource.setrlimit(resource.RLIMIT_CPU,(120,120))\n'
            + 'names=%r\ncommand=%r\nbindings={}\n' % (list(names), list(command))
            + 'for name in names:\n'
            '    fd=os.open(name,os.O_RDONLY|getattr(os,"O_NOFOLLOW",0)|getattr(os,"O_NONBLOCK",0))\n'
            '    with os.fdopen(fd,"rb") as stream:\n'
            '        info=os.fstat(stream.fileno())\n'
            '        if not stat.S_ISREG(info.st_mode) or info.st_size>%d: raise ValueError("invalid native input")\n' % (MAX_WEBP_BYTES + 5 * MAX_PIXELS)
            + '        data=stream.read(%d)\n' % (MAX_WEBP_BYTES + 5 * MAX_PIXELS + 1)
            + '    bindings[name]=hashlib.sha256(data).hexdigest()\n'
            + 'Path(%r).write_text(json.dumps(bindings,sort_keys=True))\n' % (stage + '-inputs.json')
            + 'os.execve(command[0],command,{"LANG":"C","LC_ALL":"C"})\n')


def encode_arguments(prepared):
    """The one literal encoder argument vector for a plan; never read back from a retained file."""
    return lossy_arguments(prepared['quality']) if prepared['operation'] == LOSSY else ENCODE_ARGUMENTS


def stage_commands(paths, arguments=ENCODE_ARGUMENTS):
    return {'encoder-version': ([paths['encoder'], '-version'], []),
            'decoder-version': ([paths['decoder'], '-version'], []),
            'encode': ([paths['encoder'], *arguments, 'source.pam', '-o', 'image.webp'], ['source.pam']),
            'decode': ([paths['decoder'], 'image.webp', '-pam', '-o', 'reopened.pam'], ['image.webp'])}


def launch(directory, stage, command, names):
    """One native stage through the shared cancellable runner; every launch consults the cumulative budget."""
    directory = Path(directory)
    path = directory / (stage + '-launcher.py')
    path.write_text(launcher(stage, names, command))
    try:
        execute([sys.executable, str(path)], directory, stage, remaining_timeout(STAGE_TIMEOUT), {'LANG': 'C.UTF-8'})
    except SchemaxisError as error:
        if error.fault.code != 'RUNNER_FAILED':
            raise
        target = directory / (stage + '.stderr')
        text = bounded(target, 'NATIVE_EXECUTION_FAILED', MAX_LOG_BYTES).decode('utf-8', 'replace').strip()[-200:] if target.exists() else ''
        fail('NATIVE_EXECUTION_FAILED', '%s failed (exit %s): %s' % (Path(command[0]).name, error.fault.observed.get('exitCode'), text), stage)
    return bounded(directory / (stage + '.stdout'), 'NATIVE_EXECUTION_FAILED', MAX_LOG_BYTES).decode('utf-8', 'replace')


def check_identity(stage, text):
    pattern = ENCODER_IDENTITY if stage == 'encoder-version' else DECODER_IDENTITY
    if not pattern.fullmatch(text):
        fail('UNSUPPORTED_RUNTIME', 'require an observed libwebp 1.6 %s (observed %r); other releases need upstream acceptance' % ('cwebp' if stage == 'encoder-version' else 'dwebp', text[:60]), stage)
    return text.strip()


# ---------------------------------------------------------------- lossy judgement
def refuse_deliverable(message, location, assessment, recovery):
    raise SchemaxisError(Fault('DELIVERABLE_NOT_MET', message, location, 'pipeline', False, {'assessment': assessment}, recovery))


def require_opaque(image, location='$.source'):
    """Every alpha sample must be 255: lossy VP8 output carries no alpha, and nothing is composited or discarded silently."""
    counts = pixel_counts(image['rgba'])
    if counts['opaque'] != counts['total']:
        raise SchemaxisError(Fault('WEBP_ALPHA_UNSUPPORTED', 'encodeLossy needs every pixel opaque (alpha 255); %d of %d are partly or fully transparent' % (counts['total'] - counts['opaque'], counts['total']),
                                   location, 'pipeline', False, {'pixels': counts},
                                   'publish transparency with encodeLossless, or flatten the image onto a background and re-export an opaque PNG'))


def rgb_error(source, decoded):
    """Exact integer sum of |decoded - source| over every R, G and B sample, with the sample count."""
    total = sum(sum(map(abs, map(operator.sub, source[channel::4], decoded[channel::4]))) for channel in (0, 1, 2))
    return {'sumAbsRGB': total, 'samples': len(source) // 4 * 3, 'meanAbsRGB': total / (len(source) // 4 * 3)}


def judge_bytes(prepared, webp):
    limit = prepared['budget']['maxBytes']
    if len(webp) > limit:
        refuse_deliverable('published WebP is %d bytes, above the byte budget %d' % (len(webp), limit), '$.maxBytes',
                           {'bytes': len(webp), 'maxBytes': limit, 'quality': prepared['quality']},
                           'raise maxBytes (at most %d), lower quality, or publish with encodeLossless' % MAX_WEBP_BYTES)


def budget_fraction(budget):
    """The authored budget as the exact decimal it was written as: ``str`` of a float is its shortest round-trip decimal.

    ``Fraction(0.3)`` is the binary double below 0.3, so an exact error of 18/60 would be refused against an authored 0.3.
    The plan has already refused bool, NaN, infinity and values outside 0..255, so only finite int/float arrive here.
    """
    return Fraction(str(budget))


def judge_lossy(prepared, measure):
    """Refuse unless the exact mean error is within the authored decimal budget (rational comparison, no float rounding)."""
    budget = prepared['maxMeanRGBError']
    mean = Fraction(measure['sumAbsRGB'], measure['samples'])
    if mean > budget_fraction(budget):
        refuse_deliverable('mean absolute RGB error is exactly %s (about %.6g) over %d samples, which exceeds the authored budget %s'
                           % (mean, measure['meanAbsRGB'], measure['samples'], budget), '$.maxMeanRGBError',
                           {**measure, 'meanAbsRGBExact': '%d/%d' % (mean.numerator, mean.denominator), 'maxMeanRGBError': budget, 'quality': prepared['quality']},
                           'raise maxMeanRGBError, raise quality, or publish with encodeLossless')


# ---------------------------------------------------------------- summaries and receipts
def pixel_counts(rgba):
    alpha = rgba[3::4]
    total, clear, opaque = len(alpha), alpha.count(0), alpha.count(255)
    hidden = sum(1 for a, r, g, b in zip(alpha, rgba[0::4], rgba[1::4], rgba[2::4]) if a == 0 and (r or g or b)) if clear else 0
    return {'total': total, 'opaque': opaque, 'partialAlpha': total - clear - opaque, 'transparent': clear, 'transparentWithRgb': hidden}


def summarize(image, capture, webp, header, readback):
    return {'version': SUMMARY_VERSION, 'operation': OPERATION,
            'source': {'bytes': len(capture), 'sha256': sha(capture), 'dimensions': [image['width'], image['height']],
                       'colourDeclaration': image['colourDeclaration'], 'droppedAncillaryChunks': image['droppedChunks'],
                       'rgbaSha256': sha(image['rgba'])},
            'image': {'file': 'image.webp', 'bytes': len(webp), 'sha256': sha(webp), 'dimensions': [header['width'], header['height']],
                      'container': 'RIFF WEBP simple format, one VP8L chunk', 'alphaFlag': header['alphaFlag']},
            'pixels': pixel_counts(image['rgba']),
            'readback': {'decoder': 'dwebp -pam', 'exactRgba': True, 'rgbaSha256': sha(readback)},
            'verification': 'Host strict PAM reader and RIFF/VP8L framing; every RGBA byte of a fresh native dwebp decode of the published bytes equals the PNG-decoded captured source. No independent host WebP decoder.'}


def summarize_lossy(prepared, image, capture, webp, header, readback, measure):
    return {'version': SUMMARY_VERSION, 'operation': LOSSY,
            'source': {'bytes': len(capture), 'sha256': sha(capture), 'dimensions': [image['width'], image['height']],
                       'colourDeclaration': image['colourDeclaration'], 'droppedAncillaryChunks': image['droppedChunks'],
                       'rgbaSha256': sha(image['rgba'])},
            'image': {'file': 'image.webp', 'bytes': len(webp), 'sha256': sha(webp), 'dimensions': [header['width'], header['height']],
                      'container': 'RIFF WEBP simple format, one VP8 chunk', 'alphaFlag': False},
            'request': {'quality': prepared['quality'], 'maxMeanRGBError': prepared['maxMeanRGBError'], 'maxBytes': prepared['budget']['maxBytes']},
            'error': {'meanAbsoluteRgb': measure['meanAbsRGB'], 'sumAbsoluteRgb': measure['sumAbsRGB'], 'samples': measure['samples'], 'withinBudget': True},
            'readback': {'decoder': 'dwebp -pam', 'allAlpha255': True, 'rgbaSha256': sha(readback)},
            'verification': 'Host strict RIFF/VP8 framing and PAM reader; every RGB sample of a fresh native dwebp decode of the published bytes is compared with the PNG-decoded captured source, and the exact mean absolute error and byte count are within the authored budgets. No perceptual or compression-ratio claim; no independent host WebP decoder.'}


def publications(directory, held=None, image='image.webp'):
    return [{'file': str(Path(directory) / name), 'kind': kind, 'sha256': digest(directory, name, held=held)}
            for name, kind in ((image, 'image'), ('webp-summary.json', 'text'))]


def evidence_names():
    names = {'authored.json', 'plan.json', 'captures.json', 'captured.png', 'source.pam', 'reopened.pam'}
    for stage in ('encoder-version', 'decoder-version', 'encode', 'decode'):
        names.update(stage + suffix for suffix in ('-launcher.py', '-inputs.json', '-submission.json', '.stdout', '.stderr'))
    return names


def native_decode(paths, webp):
    """Decode the exact published bytes with the trusted dwebp in a private directory; returns the PAM bytes and dwebp identity."""
    with tempfile.TemporaryDirectory(prefix='schemaxis-webp-') as scratch:
        scratch = Path(scratch)
        (scratch / 'image.webp').write_bytes(webp)
        identity = check_identity('decoder-version', launch(scratch, 'decoder-version', [paths['decoder'], '-version'], []))
        try:
            launch(scratch, 'decode', [paths['decoder'], 'image.webp', '-pam', '-o', 'reopened.pam'], ['image.webp'])
        except SchemaxisError as error:
            if error.fault.code != 'NATIVE_EXECUTION_FAILED':
                raise    # unavailable, version, timeout and cancellation faults keep their own codes
            fail('VERIFICATION_FAILED', 'published WebP bytes do not decode: ' + error.fault.message, 'image.webp', cause=error.fault.to_dict())
        decoded = bounded(scratch / 'reopened.pam', 'VERIFICATION_FAILED', 5 * MAX_PIXELS + 128)
    return decoded, identity


def fresh_decode(paths, webp, expected_rgba, width, height):
    """Decode the published bytes freshly and compare every RGBA byte."""
    decoded, identity = native_decode(paths, webp)
    decoded_width, decoded_height, pixels = read_pam(decoded)
    if (decoded_width, decoded_height) != (width, height):
        fail('VERIFICATION_FAILED', 'native decode dimensions %dx%d differ from the captured PNG %dx%d' % (decoded_width, decoded_height, width, height))
    if pixels != expected_rgba:
        first = next(i for i in range(len(pixels)) if pixels[i] != expected_rgba[i]) // 4
        fail('VERIFICATION_FAILED', 'published WebP does not decode to the captured PNG samples (first difference at pixel x=%d y=%d)' % (first % width, first // width))
    return decoded, pixels, identity


def lossy_readback(decoded, image, prepared):
    width, height, pixels = read_pam(decoded)
    if (width, height) != (image['width'], image['height']):
        fail('VERIFICATION_FAILED', 'native decode dimensions %dx%d differ from the captured PNG %dx%d' % (width, height, image['width'], image['height']))
    if pixels[3::4].count(255) != width * height:
        fail('VERIFICATION_FAILED', 'native decode of an opaque lossy WebP is not fully opaque')
    measure = rgb_error(image['rgba'], pixels)
    judge_lossy(prepared, measure)
    return pixels, measure


# ---------------------------------------------------------------- decodeToPng
def source_header(data, location='$.source'):
    """Static simple-format WebP admission before any native process: RIFF, exactly one VP8L or VP8 chunk, budgets.

    The extended format (VP8X: animation, ALPH alpha, ICC, EXIF, XMP), unknown or extra chunks and inconsistent sizes
    are refused here. Returns the chunk, the declared dimensions and the VP8L alpha hint (VP8 is always opaque).
    """
    def refuse(message, code='INVALID_WEBP_IMAGE'):
        fail(code, message + '; select one static simple-format WebP (a single VP8L or opaque VP8 chunk)', location)
    if len(data) < 25 or data[:4] != b'RIFF' or data[8:12] != b'WEBP':
        refuse('not a RIFF/WEBP file')
    if struct.unpack_from('<I', data, 4)[0] != len(data) - 8:
        refuse('RIFF size differs from the file length (truncated or trailing bytes)')
    kind, size = data[12:16], struct.unpack_from('<I', data, 16)[0]
    if kind == b'VP8X':
        if data[20] & 0x02:
            refuse('animated WebP', 'WEBP_ANIMATION_UNSUPPORTED')
        refuse('extended WebP (VP8X: ALPH alpha, ICC, EXIF or XMP) is outside the simple-format profile', 'WEBP_FORMAT_UNSUPPORTED')
    if kind not in (b'VP8L', b'VP8 '):
        refuse('first chunk %r is neither VP8L nor VP8' % kind)
    if 20 + size + (size & 1) != len(data) or (size & 1 and data[-1] != 0):
        refuse('chunk framing differs from the file length (trailing or extra chunks)')
    if kind == b'VP8L':
        if size < 5 or data[20] != 0x2f:
            refuse('VP8L signature differs')
        bits = struct.unpack_from('<I', data, 21)[0]
        if bits >> 29:
            refuse('unsupported VP8L version')
        width, height, alpha = (bits & 0x3fff) + 1, ((bits >> 14) & 0x3fff) + 1, bool((bits >> 28) & 1)
    else:
        tag = data[20] | data[21] << 8 | data[22] << 16
        if size < 10 or tag & 1 or (tag >> 1) & 7 > 3 or not (tag >> 4) & 1 or not 0 < tag >> 5 <= size - 10:
            refuse('VP8 frame tag is not a displayed key frame whose first partition fits the chunk')
        if data[23:26] != b'\x9d\x01\x2a':
            refuse('VP8 key frame start code differs')
        # The two top bits of each field are the VP8 upscaling hint; libwebp ignores them and decodes the coded size, as does this reader.
        raw_width, raw_height = struct.unpack_from('<HH', data, 26)
        width, height, alpha = raw_width & 0x3fff, raw_height & 0x3fff, False
        if not width or not height:
            refuse('VP8 dimensions are zero')
    if not (0 < width <= MAX_SIDE and 0 < height <= MAX_SIDE and width * height <= MAX_PIXELS):
        fail('WEBP_PIXEL_BUDGET', 'WebP is %dx%d; at most %d pixels per side and %d pixels are supported' % (width, height, MAX_SIDE, MAX_PIXELS), location)
    return {'chunk': kind.decode().strip(), 'width': width, 'height': height, 'alphaFlag': alpha}


def png_chunk(kind, payload):
    return struct.pack('>I', len(payload)) + kind + payload + struct.pack('>I', zlib.crc32(kind + payload) & 0xffffffff)


def encode_png(width, height, rgba, alpha):
    """Canonical PNG: signature, IHDR (8-bit RGB or RGBA, no interlace), one IDAT of filter-none rows, IEND."""
    if alpha:
        pixels = rgba
    else:
        pixels = bytearray(3 * width * height)
        for channel in range(3):
            pixels[channel::3] = rgba[channel::4]
    stride = (4 if alpha else 3) * width
    raw = b''.join(b'\0' + bytes(pixels[y * stride:(y + 1) * stride]) for y in range(height))
    header = struct.pack('>IIBBBBB', width, height, 8, 6 if alpha else 2, 0, 0, 0)
    return PNG_SIGNATURE + png_chunk(b'IHDR', header) + png_chunk(b'IDAT', zlib.compress(raw, 9)) + png_chunk(b'IEND', b'')


def read_canonical_png(data, location='image.png'):
    """Strict reader of exactly what ``encode_png`` writes; an extra chunk, filter, profile or trailing byte is refused."""
    def refuse(message):
        fail('VERIFICATION_FAILED', 'published PNG is not the canonical form: ' + message, location)
    if len(data) > MAX_PNG_BYTES or data[:8] != PNG_SIGNATURE:
        refuse('signature or size')
    offset, chunks = 8, []
    while offset < len(data):
        if offset + 12 > len(data):
            refuse('truncated chunk')
        length, kind = struct.unpack_from('>I4s', data, offset)
        end = offset + 12 + length
        if end > len(data):
            refuse('chunk length exceeds the file')
        payload = data[offset + 8:end - 4]
        if struct.unpack_from('>I', data, end - 4)[0] != zlib.crc32(kind + payload) & 0xffffffff:
            refuse('chunk checksum differs')
        chunks.append((kind, payload))
        offset = end
    if [kind for kind, _ in chunks] != [b'IHDR', b'IDAT', b'IEND'] or len(chunks[0][1]) != 13 or chunks[2][1]:
        refuse('chunks must be exactly IHDR, IDAT and IEND')
    width, height, depth, colour, compression, filtering, interlace = struct.unpack('>IIBBBBB', chunks[0][1])
    if not (0 < width <= MAX_SIDE and 0 < height <= MAX_SIDE and width * height <= MAX_PIXELS) or depth != 8 or colour not in (2, 6) or (compression, filtering, interlace) != (0, 0, 0):
        refuse('header must be 8-bit non-interlaced RGB or RGBA within the pixel budget')
    channels = 4 if colour == 6 else 3
    stride, expected = channels * width, (channels * width + 1) * height
    try:
        inflater = zlib.decompressobj()
        raw = inflater.decompress(chunks[1][1], expected + 1)
    except zlib.error:
        refuse('IDAT is not valid zlib data')
    if len(raw) != expected or not inflater.eof or inflater.unused_data or inflater.unconsumed_tail:
        refuse('IDAT does not inflate to exactly the declared rows')
    rows = [raw[y * (stride + 1):(y + 1) * (stride + 1)] for y in range(height)]
    if any(row[0] for row in rows):
        refuse('rows use a filter other than none')
    body = b''.join(row[1:] for row in rows)
    if colour == 6:
        rgba = bytes(body)
    else:
        rgba = bytearray(4 * width * height)
        for channel in range(3):
            rgba[channel::4] = body[channel::3]
        rgba[3::4] = b'\xff' * (width * height)
        rgba = bytes(rgba)
    return {'width': width, 'height': height, 'alpha': colour == 6, 'rgba': rgba}


def decode_command(paths):
    return [paths['decoder'], 'captured.webp', *DECODE_ARGUMENTS, '-o', 'decoded.pam']


def decode_names():
    names = {'authored.json', 'plan.json', 'captures.json', 'captured.webp', 'decoded.pam'}
    for stage in ('decoder-version', 'decode'):
        names.update(stage + suffix for suffix in ('-launcher.py', '-inputs.json', '-submission.json', '.stdout', '.stderr'))
    return names


def native_report(text, header):
    """dwebp's own statement of what it decoded must agree with the host's framing read, before the pixels are trusted."""
    found = NATIVE_REPORT.fullmatch(text)
    chunk = 'lossless' if header['chunk'] == 'VP8L' else 'lossy'
    if not found or (int(found.group(1)), int(found.group(2))) != (header['width'], header['height']) or found.group(4) != chunk or bool(found.group(3)) != header['alphaFlag']:
        fail('VERIFICATION_FAILED', 'dwebp reports a decode that differs from the WebP framing (observed %r)' % text[:120], 'decode')
    return {'dimensions': [int(found.group(1)), int(found.group(2))], 'format': found.group(4), 'withAlpha': bool(found.group(3))}


def decoded_pixels(pam_bytes, header):
    width, height, pixels = read_pam(pam_bytes)
    if (width, height) != (header['width'], header['height']):
        fail('VERIFICATION_FAILED', 'native decode dimensions %dx%d differ from the WebP framing %dx%d' % (width, height, header['width'], header['height']))
    if not header['alphaFlag'] and pixels[3::4].count(255) != width * height:
        raise SchemaxisError(Fault('WEBP_ALPHA_MISMATCH', 'the WebP declares no alpha but %d of %d decoded pixels are not opaque' % (width * height - pixels[3::4].count(255), width * height),
                                   'decode', 'pipeline', False, {'alphaFlag': False}, 'select a WebP whose alpha hint matches its pixels; lossless files from cwebp set it when any pixel is transparent'))
    return pixels


def native_decode_source(paths, webp, header):
    """Decode the exact captured bytes with the trusted dwebp in a private directory: PAM bytes, identity, dwebp's report."""
    with tempfile.TemporaryDirectory(prefix='schemaxis-webp-') as scratch:
        scratch = Path(scratch)
        (scratch / 'captured.webp').write_bytes(webp)
        identity = check_identity('decoder-version', launch(scratch, 'decoder-version', [paths['decoder'], '-version'], []))
        try:
            launch(scratch, 'decode', decode_command(paths), ['captured.webp'])
        except SchemaxisError as error:
            if error.fault.code != 'NATIVE_EXECUTION_FAILED':
                raise
            fail('VERIFICATION_FAILED', 'captured WebP bytes do not decode: ' + error.fault.message, 'captured.webp', cause=error.fault.to_dict())
        decoded = bounded(scratch / 'decoded.pam', 'VERIFICATION_FAILED', 5 * MAX_PIXELS + 128)
        report = native_report(bounded(scratch / 'decode.stderr', 'VERIFICATION_FAILED', MAX_LOG_BYTES).decode('utf-8', 'replace'), header)
    return decoded, identity, report


def summarize_decode(capture, header, png_bytes, png_image, readback, report):
    return {'version': SUMMARY_VERSION, 'operation': DECODE,
            'source': {'file': 'captured.webp', 'bytes': len(capture), 'sha256': sha(capture), 'dimensions': [header['width'], header['height']],
                       'container': 'RIFF WEBP simple format, one %s chunk' % ('VP8L' if header['chunk'] == 'VP8L' else 'VP8'), 'alphaFlag': header['alphaFlag']},
            'image': {'file': 'image.png', 'bytes': len(png_bytes), 'sha256': sha(png_bytes), 'dimensions': [png_image['width'], png_image['height']],
                      'format': 'PNG 8-bit %s, chunks IHDR IDAT IEND, filter none' % ('RGBA' if png_image['alpha'] else 'RGB'), 'colourDeclaration': 'untagged (treat as sRGB)'},
            'pixels': pixel_counts(readback),
            'readback': {'decoder': 'dwebp -nodither -pam', 'report': report, 'rgbaSha256': sha(readback), 'pngRgbaSha256': sha(png_image['rgba']), 'exactRgba': True},
            'verification': 'Host strict RIFF framing; every RGBA sample of a fresh native dwebp decode of the captured WebP equals the published PNG as read by the strict canonical reader and by the shared bounded PNG decoder. Semantic agreement with libwebp, not an independent host WebP decoder; the source is not authenticated.'}


def check_png(png_bytes, readback, header):
    """The published PNG against the native pixels, by two independent host readers and the framing's dimensions."""
    image = read_canonical_png(png_bytes)
    if (image['width'], image['height']) != (header['width'], header['height']) or image['alpha'] != header['alphaFlag']:
        fail('VERIFICATION_FAILED', 'published PNG dimensions or colour type differ from the WebP framing', 'image.png')
    if image['rgba'] != readback:
        first = next(i for i in range(len(readback)) if image['rgba'][i] != readback[i]) // 4
        fail('VERIFICATION_FAILED', 'published PNG does not equal the native WebP decode (first difference at pixel x=%d y=%d)' % (first % image['width'], first // image['width']), 'image.png')
    try:
        shared = png.decode(png_bytes)
    except SchemaxisError as error:
        fail('VERIFICATION_FAILED', 'shared PNG decoder refuses the published PNG: ' + error.fault.message, 'image.png', cause=error.fault.to_dict())
    if (shared[0], shared[1]) != (image['width'], image['height']) or bytes(shared[2]) != readback:
        fail('VERIFICATION_FAILED', 'shared PNG decoder disagrees with the native WebP decode', 'image.png')
    return image


def decode_publication(prepared, directory, paths):
    """Run decodeToPng into a fresh directory: capture once, decode natively, publish, then verify from the retained files."""
    capture = bounded(prepared['source'], 'INVALID_WEBP_SOURCE', MAX_WEBP_BYTES, '$.source')
    header = source_header(capture)
    (directory / 'captured.webp').write_bytes(capture)
    atomic_json(directory / 'captures.json', {'source': prepared['source'], 'bytes': len(capture), 'sha256': sha(capture)})
    check_identity('decoder-version', launch(directory, 'decoder-version', [paths['decoder'], '-version'], []))
    try:
        launch(directory, 'decode', decode_command(paths), ['captured.webp'])
    except SchemaxisError as error:
        if error.fault.code != 'NATIVE_EXECUTION_FAILED':
            raise
        fail('INVALID_WEBP_IMAGE', 'dwebp cannot decode the captured WebP: ' + error.fault.message, '$.source', cause=error.fault.to_dict(),
             recovery='select an intact static simple-format WebP')
    decoded = bounded(directory / 'decoded.pam', 'NATIVE_EXECUTION_FAILED', 5 * MAX_PIXELS + 128)
    report = native_report(bounded(directory / 'decode.stderr', 'NATIVE_EXECUTION_FAILED', MAX_LOG_BYTES).decode('utf-8', 'replace'), header)
    readback = decoded_pixels(decoded, header)
    png_bytes = encode_png(header['width'], header['height'], readback, header['alphaFlag'])
    (directory / 'image.png').write_bytes(png_bytes)
    summary = summarize_decode(capture, header, png_bytes, check_png(png_bytes, readback, header), readback, report)
    atomic_json(directory / 'webp-summary.json', summary)
    atomic_json(directory / 'verification.json', {
        'artifacts': publications(directory, image='image.png'), 'evidence': {n: digest(directory, n) for n in sorted(decode_names())},
        'runtime': {'decoder': (directory / 'decoder-version.stdout').read_text().strip()}, 'executables': paths})
    result = verify_semantic(directory, paths, require_result=False)
    remaining_timeout(STAGE_TIMEOUT)
    return {'status': 'succeeded', **result}


# ---------------------------------------------------------------- run
def run(document, directory, *, executable=None, decoder=None, timeout=300):
    prepared = plan(document)
    if os.name != 'posix':
        fail('UNSUPPORTED_PLATFORM', 'native resource caps require POSIX')
    if type(timeout) not in (int, float) or not math.isfinite(timeout) or not 0 < timeout <= 3600:
        fail('INVALID_ARGUMENT', 'timeout must be finite and in (0,3600]')
    paths = runtime(executable, decoder, need_encoder=prepared['operation'] != DECODE)
    directory = Path(directory).absolute()
    if directory.exists() or directory.is_symlink():
        fail('OUTPUT_EXISTS', 'select a fresh WebP publication directory', str(directory))
    try:
        directory.mkdir(parents=True)
    except FileExistsError:
        fail('OUTPUT_EXISTS', 'select a fresh WebP publication directory', str(directory))
    atomic_json(directory / 'authored.json', document)
    atomic_json(directory / 'plan.json', prepared)
    atomic_json(directory / 'result.json', {'status': 'incomplete', 'verified': False})
    try:
        with execution_deadline(timeout):
            if prepared['operation'] == DECODE:
                result = decode_publication(prepared, directory, paths)
                atomic_json(directory / 'result.json', result)
                return result
            capture = bounded(prepared['source'], 'INVALID_WEBP_SOURCE', MAX_SOURCE_BYTES, '$.source')
            image = admit_png(capture)
            if prepared['operation'] == LOSSY:
                require_opaque(image)
            (directory / 'captured.png').write_bytes(capture)
            (directory / 'source.pam').write_bytes(pam(image['width'], image['height'], image['rgba']))
            atomic_json(directory / 'captures.json', {'source': prepared['source'], 'bytes': len(capture), 'sha256': sha(capture)})
            commands = stage_commands(paths, encode_arguments(prepared))
            for stage in ('encoder-version', 'decoder-version'):
                check_identity(stage, launch(directory, stage, *commands[stage]))
            for stage in ('encode', 'decode'):
                launch(directory, stage, *commands[stage])
            webp = bounded(directory / 'image.webp', 'NATIVE_EXECUTION_FAILED', MAX_WEBP_BYTES)
            decoded = bounded(directory / 'reopened.pam', 'NATIVE_EXECUTION_FAILED', 5 * MAX_PIXELS + 128)
            if prepared['operation'] == LOSSY:
                header = vp8_header(webp)
                judge_bytes(prepared, webp)
                readback, measure = lossy_readback(decoded, image, prepared)   # refuses before any summary or receipt is written
                summary = summarize_lossy(prepared, image, capture, webp, header, readback, measure)
            else:
                header = webp_header(webp)
                summary = summarize(image, capture, webp, header, read_pam(decoded)[2])
            atomic_json(directory / 'webp-summary.json', summary)
            runtimes = {stage[:7]: (directory / (stage + '.stdout')).read_text().strip() for stage in ('encoder-version', 'decoder-version')}
            atomic_json(directory / 'verification.json', {
                'artifacts': publications(directory), 'evidence': {n: digest(directory, n) for n in sorted(evidence_names())},
                'runtime': {'encoder': runtimes['encoder'], 'decoder': runtimes['decoder']}, 'executables': paths})
            result = verify_semantic(directory, paths, require_result=False)
            remaining_timeout(STAGE_TIMEOUT)
            result = {'status': 'succeeded', **result}
            atomic_json(directory / 'result.json', result)
            return result
    except Exception as error:
        if not isinstance(error, SchemaxisError):
            try:
                fail('NATIVE_EXECUTION_FAILED', str(error))
            except SchemaxisError as wrapped:
                error = wrapped
        atomic_json(directory / 'result.json', {'status': 'failed', 'verified': False, 'fault': error.fault.to_dict()})
        raise error


# ---------------------------------------------------------------- verification
def result_claims(result):
    """Every claim of a result record, closed: an unknown, missing, promoted or mistyped field is a difference.

    Only ``status`` (checked separately) and the text of ``runtime.freshDecoder`` are excluded, because that identity
    legitimately varies with the verifying dwebp; it must still be present and a libwebp 1.6 identity string.
    """
    claims = {key: value for key, value in result.items() if key != 'status'}
    runtime_record = claims.get('runtime')
    if isinstance(runtime_record, dict):
        fresh = runtime_record.get('freshDecoder')
        claims['runtime'] = {**{key: value for key, value in runtime_record.items() if key != 'freshDecoder'},
                             'freshDecoder': isinstance(fresh, str) and DECODER_IDENTITY.fullmatch(fresh) is not None}
    return claims


def verify_decode(directory, paths, prepared, recorded_result, require_result):
    """decodeToPng judgement: the captured WebP, decoded freshly by the trusted dwebp, must equal every sample of image.png.

    The captured WebP, PNG, run readback and summary are each read once and held; the receipt digests and the native
    input binding are compared with those very bytes. The original source path is never read again.
    """
    held = {}
    capture = held['captured.webp'] = bounded(directory / 'captured.webp', limit=MAX_WEBP_BYTES)
    if not same_json(read_json(directory, 'captures.json'), {'source': prepared['source'], 'bytes': len(capture), 'sha256': sha(capture)}):
        fail('VERIFICATION_FAILED', 'WebP source capture record differs from the captured bytes')
    try:
        header = source_header(capture, 'captured.webp')
    except SchemaxisError as error:
        fail('VERIFICATION_FAILED', 'retained captured WebP is invalid: ' + error.fault.message, cause=error.fault.to_dict())
    decoded, decoder_identity, report = native_decode_source(paths, capture, header)
    try:
        readback = decoded_pixels(decoded, header)
    except SchemaxisError as error:
        if error.fault.code != 'WEBP_ALPHA_MISMATCH':
            raise
        fail('VERIFICATION_FAILED', 'fresh native decode of the captured WebP contradicts its alpha hint: ' + error.fault.message, 'captured.webp', cause=error.fault.to_dict())
    if held.setdefault('decoded.pam', bounded(directory / 'decoded.pam', limit=5 * MAX_PIXELS + 128)) != decoded:
        fail('VERIFICATION_FAILED', 'retained run readback differs from the fresh native decode')
    png_bytes = held['image.png'] = bounded(directory / 'image.png', limit=MAX_PNG_BYTES)
    image = check_png(png_bytes, readback, header)
    if native_report(bounded(directory / 'decode.stderr', limit=MAX_LOG_BYTES).decode('utf-8', 'replace'), header)['dimensions'] != [header['width'], header['height']]:
        fail('VERIFICATION_FAILED', 'retained dwebp report differs from the WebP framing')
    summary = held['webp-summary.json'] = bounded(directory / 'webp-summary.json', limit=MAX_LOG_BYTES)
    if not same_json(strict_json(summary, 'webp-summary.json'), summarize_decode(capture, header, png_bytes, image, readback, report)):
        fail('VERIFICATION_FAILED', 'retained summary differs from the recomputed observation')
    receipt = read_json(directory, 'verification.json')
    if not isinstance(receipt, dict) or not same_json(receipt.get('artifacts'), publications(directory, held, 'image.png')):
        fail('VERIFICATION_FAILED', 'publication membership or digests differ from the receipt')
    evidence = receipt.get('evidence')
    if not isinstance(evidence, dict) or set(evidence) != decode_names():
        fail('VERIFICATION_FAILED', 'retained evidence membership differs')
    for name in decode_names():
        if digest(directory, name, held=held) != evidence[name]:
            fail('VERIFICATION_FAILED', 'retained evidence differs', name)
    recorded = receipt.get('executables')
    if not isinstance(recorded, dict) or set(recorded) != {'decoder'} or not isinstance(recorded['decoder'], str) or not os.path.isabs(recorded['decoder']):
        fail('VERIFICATION_FAILED', 'receipt executable identity must be absolute provenance')
    runtimes = receipt.get('runtime')
    observed = check_identity('decoder-version', bounded(directory / 'decoder-version.stdout', limit=MAX_LOG_BYTES).decode('utf-8', 'replace'))
    if not isinstance(runtimes, dict) or set(runtimes) != {'decoder'} or runtimes['decoder'] != observed:
        fail('VERIFICATION_FAILED', 'recorded runtime identity differs from the retained version output', 'decoder-version')
    for stage, (command, names) in {'decoder-version': ([recorded['decoder'], '-version'], []), 'decode': (decode_command(recorded), ['captured.webp'])}.items():
        submission = read_json(directory, stage + '-submission.json')
        interpreter = submission.get('interpreter', {}).get('executable') if isinstance(submission.get('interpreter'), dict) else None
        native = submission.get('nativeCommand')
        if (not isinstance(interpreter, str) or not os.path.isabs(interpreter) or not isinstance(native, list) or len(native) != 2
                or native[0] != interpreter or Path(native[1]).name != stage + '-launcher.py'
                or type(submission.get('exitCode')) is not int or submission['exitCode'] != 0):
            fail('VERIFICATION_FAILED', 'native command or completion record differs', stage)
        if bounded(directory / (stage + '-launcher.py'), limit=MAX_LOG_BYTES).decode() != launcher(stage, names, command):
            fail('VERIFICATION_FAILED', 'trusted native launcher differs', stage)
        if not same_json(read_json(directory, stage + '-inputs.json'), {name: digest(directory, name, MAX_WEBP_BYTES, held) for name in names}):
            fail('VERIFICATION_FAILED', 'native input binding differs', stage)
    remaining_timeout(VERIFY_TIMEOUT)
    verified = {'verified': True, 'operation': DECODE, 'artifacts': 2, 'dimensions': [header['width'], header['height']], 'bytes': len(png_bytes),
                'sourceBytes': len(capture), 'runtime': {'decoder': runtimes['decoder'], 'freshDecoder': decoder_identity}}
    if require_result and not same_json(result_claims(recorded_result), result_claims(verified)):
        fail('VERIFICATION_FAILED', 'retained result claims differ from the verified observation')
    return verified


def verify_semantic(directory, paths, require_result=True):
    """Judge the published bytes from the authored request, captured PNG and a fresh native decode.

    The decision is: the actual image.webp bytes pass strict RIFF/VP8L framing and the trusted dwebp, run now in a
    separate process on a private copy of those bytes, reproduces every RGBA byte of the PNG-decoded captured source.
    Retained files are hash-bound consistency diagnostics: plan, capture record, canonical PAM bridge, the run's own
    readback, the encode log's reported size, launchers/input bindings/exit codes (never re-executed), the summary and
    the receipt's membership. Retained JSON is read strictly (no duplicate keys or non-finite numbers) and compared by
    typed canonical form. The pixel-related sources, encoded bytes, readback and summary are held from one read;
    the image digest and decode-input binding use the same held WebP snapshot. Other provenance files may be read again
    for hashing. The receipt therefore binds the bytes that were decoded. Receipt executables are inert provenance and are never launched. The judgement covers the
    bytes read during this call only; a writer that changes the directory afterwards is not guarded against.
    """
    directory = Path(directory).absolute()
    try:
        with execution_deadline(VERIFY_TIMEOUT):
            try:
                prepared = plan(read_json(directory, 'authored.json'))
            except SchemaxisError as error:
                fail('VERIFICATION_FAILED', 'retained authored input is invalid: ' + error.fault.message, str(directory))
            if not same_json(read_json(directory, 'plan.json'), prepared):
                fail('VERIFICATION_FAILED', 'retained plan differs from the authored input')
            recorded_result = read_json(directory, 'result.json') if require_result else None
            if require_result and (not isinstance(recorded_result, dict) or recorded_result.get('status') != 'succeeded'):
                fail('INCOMPLETE_EXECUTION', 'WebP publication did not complete')
            if prepared['operation'] == DECODE:
                return verify_decode(directory, paths, prepared, recorded_result, require_result)
            held = {}
            capture = held['captured.png'] = bounded(directory / 'captured.png', limit=MAX_SOURCE_BYTES)
            if not same_json(read_json(directory, 'captures.json'), {'source': prepared['source'], 'bytes': len(capture), 'sha256': sha(capture)}):
                fail('VERIFICATION_FAILED', 'PNG source capture record differs from the captured bytes')
            try:
                image = admit_png(capture)
                if prepared['operation'] == LOSSY:
                    require_opaque(image)
            except SchemaxisError as error:
                fail('VERIFICATION_FAILED', 'retained captured PNG is invalid: ' + error.fault.message, cause=error.fault.to_dict())
            bridge = held['source.pam'] = bounded(directory / 'source.pam', limit=5 * MAX_PIXELS + 128)
            if bridge != pam(image['width'], image['height'], image['rgba']):
                fail('VERIFICATION_FAILED', 'canonical PAM bridge differs from the captured PNG')
            webp = held['image.webp'] = bounded(directory / 'image.webp', limit=MAX_WEBP_BYTES)
            lossy = prepared['operation'] == LOSSY
            header = vp8_header(webp) if lossy else webp_header(webp)
            if (header['width'], header['height']) != (image['width'], image['height']):
                fail('VERIFICATION_FAILED', 'WebP dimensions differ from the captured PNG')
            if lossy:
                judge_bytes(prepared, webp)
                decoded, decoder_identity = native_decode(paths, webp)
                readback, measure = lossy_readback(decoded, image, prepared)
            else:
                decoded, readback, decoder_identity = fresh_decode(paths, webp, image['rgba'], image['width'], image['height'])
            if held.setdefault('reopened.pam', bounded(directory / 'reopened.pam', limit=5 * MAX_PIXELS + 128)) != decoded:
                fail('VERIFICATION_FAILED', 'retained run readback differs from the fresh native decode')
            reported = re.search(rb'Output:\s+(\d+) bytes', bounded(directory / 'encode.stderr', limit=MAX_LOG_BYTES))
            if not reported or int(reported.group(1)) != len(webp):
                fail('VERIFICATION_FAILED', 'encode log size does not match the published WebP bytes')
            summary = held['webp-summary.json'] = bounded(directory / 'webp-summary.json', limit=MAX_LOG_BYTES)
            expected = summarize_lossy(prepared, image, capture, webp, header, readback, measure) if lossy else summarize(image, capture, webp, header, readback)
            if not same_json(strict_json(summary, 'webp-summary.json'), expected):
                fail('VERIFICATION_FAILED', 'retained summary differs from the recomputed observation')
            receipt = read_json(directory, 'verification.json')
            if not isinstance(receipt, dict) or not same_json(receipt.get('artifacts'), publications(directory, held)):
                fail('VERIFICATION_FAILED', 'publication membership or digests differ from the receipt')
            evidence = receipt.get('evidence')
            if not isinstance(evidence, dict) or set(evidence) != evidence_names():
                fail('VERIFICATION_FAILED', 'retained evidence membership differs')
            for name in evidence_names():
                if digest(directory, name, held=held) != evidence[name]:
                    fail('VERIFICATION_FAILED', 'retained evidence differs', name)
            recorded = receipt.get('executables')
            if not isinstance(recorded, dict) or set(recorded) != {'encoder', 'decoder'} or not all(isinstance(v, str) and os.path.isabs(v) for v in recorded.values()):
                fail('VERIFICATION_FAILED', 'receipt executable identity must be absolute provenance')
            runtimes = receipt.get('runtime')
            for stage in ('encoder-version', 'decoder-version'):
                observed = check_identity(stage, bounded(directory / (stage + '.stdout'), limit=MAX_LOG_BYTES).decode('utf-8', 'replace'))
                if not isinstance(runtimes, dict) or runtimes.get(stage[:7]) != observed:
                    fail('VERIFICATION_FAILED', 'recorded runtime identity differs from the retained version output', stage)
            for stage, (command, names) in stage_commands(recorded, encode_arguments(prepared)).items():
                submission = read_json(directory, stage + '-submission.json')
                interpreter = submission.get('interpreter', {}).get('executable') if isinstance(submission.get('interpreter'), dict) else None
                native = submission.get('nativeCommand')
                if (not isinstance(interpreter, str) or not os.path.isabs(interpreter) or not isinstance(native, list) or len(native) != 2
                        or native[0] != interpreter or Path(native[1]).name != stage + '-launcher.py'
                        or type(submission.get('exitCode')) is not int or submission['exitCode'] != 0):
                    fail('VERIFICATION_FAILED', 'native command or completion record differs', stage)
                if bounded(directory / (stage + '-launcher.py'), limit=MAX_LOG_BYTES).decode() != launcher(stage, names, command):
                    fail('VERIFICATION_FAILED', 'trusted native launcher differs', stage)
                # The decode stage's only input is image.webp, bound here to the same snapshot that was decoded above.
                if not same_json(read_json(directory, stage + '-inputs.json'), {name: digest(directory, name, 5 * MAX_PIXELS + 128, held) for name in names}):
                    fail('VERIFICATION_FAILED', 'native input binding differs', stage)
            remaining_timeout(VERIFY_TIMEOUT)
            verified = {'verified': True, 'artifacts': 2, 'dimensions': [image['width'], image['height']], 'bytes': len(webp),
                        'runtime': {'encoder': runtimes['encoder'], 'decoder': runtimes['decoder'], 'freshDecoder': decoder_identity}}
            if lossy:
                verified['operation'] = LOSSY
                verified['error'] = {'meanAbsoluteRgb': measure['meanAbsRGB'], 'sumAbsoluteRgb': measure['sumAbsRGB'], 'samples': measure['samples'], 'maxMeanRGBError': prepared['maxMeanRGBError'],
                                     'maxBytes': prepared['budget']['maxBytes']}
            if require_result and not same_json(result_claims(recorded_result), result_claims(verified)):
                fail('VERIFICATION_FAILED', 'retained result claims differ from the verified observation')
            return verified
    except (OSError, ValueError, KeyError, TypeError, IndexError, AttributeError, UnicodeError, RecursionError, StopIteration) as error:
        fail('VERIFICATION_FAILED', 'invalid retained WebP evidence: %s %s' % (type(error).__name__, str(error)[:80]))


def verify(directory, require_result=True, *, decoder=None):
    return verify_semantic(directory, runtime(decoder=decoder, need_encoder=False), require_result)


from schemaxis.adaptor_runtime import bind as _bind_runtime
_bind_runtime(globals())
