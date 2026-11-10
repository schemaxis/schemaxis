"""Bounded lossless FLAC archive and PCM16 decode, verified by fresh native decoding.

``encodeLossless`` archives one PCM16 WAV as native FLAC; ``decodePCM16`` turns one native FLAC
into a canonical PCM16 WAV that the speech-preparation adaptors accept. The host parses the WAV
(or the FLAC STREAMINFO, metadata framing and first frame header) independently and passes the
trusted ``flac`` raw PCM, never a container. There is no host FLAC decoder: verification needs
the separately configured trusted ``flac``, which re-decodes the actual FLAC bytes in a private
directory. The host then compares every PCM byte, recomputes the MD5 over the decoded samples
and checks STREAMINFO. Receipts never supply an executable.

``encodeLossless`` may also carry up to three author-declared recording labels (title, artist,
description) as native VORBIS_COMMENT tags. They are data: the field names and the argument
shapes are fixed, the host parses the published VORBIS_COMMENT itself, and the labels are neither
an identity nor a rights claim. Without labels the encode is unchanged and the comment is empty.
"""
from array import array
import hashlib
import io
import json
import math
import os
from pathlib import Path
import re
import stat
import struct
import sys
import tempfile
import unicodedata
import wave

from schemaxis.artifacts import atomic_json
from schemaxis.configuration import executable as configured_executable
from schemaxis.core.declarations import validate_arguments
from schemaxis.core.faults import SchemaxisError
from schemaxis.dispatch import execution_deadline, remaining_timeout
from schemaxis.errors import fail, keys
from schemaxis.native_command import execute

VERSION = 'schemaxis.flac/1'
OPERATIONS = ('encodeLossless', 'decodePCM16')
PLAN_VERSION = 'schemaxis.flac.plan/1'
SUMMARY_VERSION = 'schemaxis.flac.summary/1'
MAX_SECONDS = 600
MAX_WAV_BYTES = 32 * 1024 * 1024        # the SoX conform source limit: every decoded WAV stays admissible downstream
WAV_HEADER = 44
MAX_PCM_BYTES = MAX_WAV_BYTES - WAV_HEADER
MAX_FLAC_BYTES = 40 * 1024 * 1024
MAX_METADATA_BYTES = 4 * 1024 * 1024
MAX_LOG_BYTES = 1024 * 1024
OUTPUT_SLACK = 1024 * 1024
STAGE_TIMEOUT = 180
VERIFY_TIMEOUT = 300
RATE_MIN, RATE_MAX = 8000, 192000
ENCODE_ARGUMENTS = ['-8', '-V', '-s', '-w', '--no-padding', '--no-seektable', '--no-preserve-modtime',
                    '--force-raw-format', '--endian=little', '--sign=signed', '--bps=16']
DECODE_ARGUMENTS = ['-d', '-s', '-w', '--no-preserve-modtime', '--force-raw-format', '--endian=little', '--sign=signed']
IDENTITY = re.compile(r'flac 1\.5\.\d+\n?')
VENDOR = re.compile(rb'reference libFLAC 1\.5\.\d+ \d{8}')
SUFFIX = {'encodeLossless': '.wav', 'decodePCM16': '.flac'}
BLOCK_TYPES = {0: 'STREAMINFO', 1: 'PADDING', 2: 'APPLICATION', 3: 'SEEKTABLE', 4: 'VORBIS_COMMENT', 5: 'CUESHEET', 6: 'PICTURE'}
BLOCK_SIZES = {1: 192, 2: 576, 3: 1152, 4: 2304, 5: 4608, 8: 256, 9: 512, 10: 1024, 11: 2048, 12: 4096, 13: 8192, 14: 16384, 15: 32768}
RATE_CODES = {1: 88200, 2: 176400, 3: 192000, 4: 8000, 5: 16000, 6: 22050, 7: 24000, 8: 32000, 9: 44100, 10: 48000, 11: 96000}
LABEL_FIELDS = (('title', 'TITLE', 200, 512), ('artist', 'ARTIST', 200, 512), ('description', 'DESCRIPTION', 1000, 3000))
LABEL_BIDI = frozenset([0x061c, 0x200e, 0x200f, *range(0x202a, 0x202f), *range(0x2066, 0x206a)])
LABEL_JOINERS = frozenset([0x200c, 0x200d])
UTF8_ARGUMENT = '--no-utf8-convert'
SOURCE_FAULTS = ('INVALID_FLAC_SOURCE', 'INVALID_FLAC_WAV', 'INVALID_FLAC_STREAM', 'UNSUPPORTED_FLAC_FORMAT', 'FLAC_BUDGET')

OPTIONS = {'source': {'type': 'string', 'minLength': 1, 'maxLength': 4096, 'required': True}}
LABEL_OPTION = {'type': 'object', 'properties': {key: {'type': 'string', 'minLength': 1, 'maxLength': chars} for key, _, chars, _ in LABEL_FIELDS}}
DECLARATIONS = {name: {
    'native': native, 'kinds': ['file', 'text'], 'inputs': {},
    'options': {k: {'value': v} for k, v in {**OPTIONS, **({'metadata': LABEL_OPTION} if name == 'encodeLossless' else {})}.items()}}
    for name, native in (
        ('encodeLossless', 'flac -8 -V -s -w --no-padding --no-seektable --no-preserve-modtime --force-raw-format --endian=little --sign=signed --channels=N --bps=16 --sample-rate=R -o audio.flac source.pcm '
                           '(with authored metadata labels also: --no-utf8-convert --tag=TITLE=T --tag=ARTIST=A --tag=DESCRIPTION=D, fixed order, one argument per value); '
                           'flac -d -s -w --no-preserve-modtime --force-raw-format --endian=little --sign=signed -o reopened.pcm audio.flac (FLAC 1.5)'),
        ('decodePCM16', 'flac -d -s -w --no-preserve-modtime --force-raw-format --endian=little --sign=signed -o decoded.pcm captured.flac (FLAC 1.5); host wraps the PCM in a canonical 44-byte WAV'))}
LOSSES = [
    'Audio is signed 16-bit PCM, mono or stereo, 8000-192000 Hz, at most 600 seconds. The decoded canonical WAV (44-byte header plus PCM) is at most 32 MiB, the SoX conform source limit; larger, 24-bit, float, multichannel and unknown-length audio are refused.',
    'encodeLossless accepts the same PCM16 WAV subset as the SoX adaptor (a 16-byte fmt chunk, data, optional LIST and JUNK, listed and dropped) and publishes a native FLAC file. The encoder is fixed (-8, verified, no padding, no seek table); there are no authored flags and no metadata, tags, pictures or cue points are carried.',
    'decodePCM16 accepts native FLAC only, starting at byte 0 with fLaC: no Ogg FLAC, ID3 prefixes, lossy, non-16-bit, more than two channels, zero or unknown total sample count or all-zero STREAMINFO MD5. Tags, pictures, seek tables, padding, application blocks and cue sheets are listed in the summary and dropped. The output is a canonical PCM16 WAV.',
    'The host checks STREAMINFO, the metadata block framing and the first frame header (including its CRC-8) before any native process starts; the frame bodies are decoded only by libFLAC. Decoding never uses --decode-through-errors, so damaged frames are refused rather than concealed.',
    'Verification re-decodes the actual FLAC bytes with a separately configured trusted flac; Schemaxis has no independent host FLAC decoder and does not claim host-independent bitstream verification. For encodeLossless every PCM byte of the decode equals the PCM of the captured WAV. For decodePCM16 the PCM must agree with the STREAMINFO sample count and MD5, which is internal consistency of the file: it does not certify that the recording is authentic or unaltered.']
LABELLED_LOSSES = [
    LOSSES[0],
    'encodeLossless accepts the same PCM16 WAV subset as the SoX adaptor (a 16-byte fmt chunk, data, optional LIST and JUNK, listed and dropped) and publishes a native FLAC file. The encoder is fixed (-8, verified, no padding, no seek table); there are no authored flags. '
    'The only metadata carried is the authored title, artist and description labels as one VORBIS_COMMENT tag each; WAV LIST and JUNK text, pictures, cue points and every other tag are not carried.',
    LOSSES[2], LOSSES[3], LOSSES[4],
    'The labels are author-declared text stored exactly as authored (no trimming or Unicode normalisation), at most 200, 200 and 1000 code points and 512, 512 and 3000 UTF-8 bytes. They are not an identity, licence, rights or provenance certificate, and a coherent rewrite of the request, the FLAC and the retained records verifies as semantic consistency, not authenticity. '
    'decodePCM16 still drops tags, so labels do not travel through a decode.']


# ---------------------------------------------------------------- planning
def label_value(key, value, chars, size, location):
    """One authored label as exact plain UTF-8 text, or INVALID_FLAC_METADATA; nothing is trimmed, normalised or cropped."""
    def refuse(message):
        fail('INVALID_FLAC_METADATA', 'metadata.%s %s' % (key, message), location, recovery='write one nonempty visible plain-text label within the documented limits')
    if type(value) is not str:
        refuse('must be a string')
    if not value:
        refuse('must not be empty')
    if len(value) > chars:
        refuse('is longer than %d code points' % chars)
    visible = False
    for char in value:
        code, category = ord(char), unicodedata.category(char)
        if 0xd800 <= code <= 0xdfff:
            refuse('contains a lone surrogate, which is not UTF-8 text')
        if code in LABEL_BIDI:
            refuse('contains a bidirectional control character (U+%04X)' % code)
        if category == 'Cc':
            refuse('contains a control character (U+%04X), including newlines and tabs' % code)
        if category in ('Zl', 'Zp', 'Co') or (category == 'Cf' and code not in LABEL_JOINERS) or 0xfdd0 <= code <= 0xfdef or code & 0xfffe == 0xfffe:
            refuse('contains a line or paragraph separator, invisible, private-use or noncharacter code point (U+%04X)' % code)
        visible = visible or category[0] in 'LNPS'
    if not visible:
        refuse('needs at least one visible letter, number, punctuation mark or symbol')
    if len(value.encode('utf-8')) > size:
        refuse('is longer than %d UTF-8 bytes' % size)
    return value


def labels(value, location='$.metadata'):
    """Validated authored labels (all present keys, in the fixed order title, artist, description); a present but non-object value is refused."""
    if not isinstance(value, dict):
        fail('INVALID_FLAC_METADATA', 'metadata must be an object with title, artist or description', location)
    extra = sorted(set(value) - {key for key, *_ in LABEL_FIELDS})
    if extra:
        fail('UNKNOWN_ARGUMENT', 'unsupported keys', location, keys=extra)
    if not value:
        fail('INVALID_FLAC_METADATA', 'metadata must carry at least one of title, artist or description; omit it for none', location)
    return {key: label_value(key, value[key], chars, size, '%s.%s' % (location, key)) for key, _, chars, size in LABEL_FIELDS if key in value}


def tag_arguments(authored):
    """Native tag arguments for validated labels: fixed field names, one argument per value, never shell-parsed."""
    return [UTF8_ARGUMENT, *['--tag=%s=%s' % (field, authored[key]) for key, field, _, _ in LABEL_FIELDS if key in authored]] if authored else []


def comment_lines(authored):
    """The exact VORBIS_COMMENT entries (bytes, in order) the native encode must publish for these labels."""
    return [('%s=%s' % (field, authored[key])).encode('utf-8') for key, field, _, _ in LABEL_FIELDS if key in authored] if authored else []


def encode_arguments(authored=None):
    return ENCODE_ARGUMENTS + tag_arguments(authored)


def plan(document):
    keys(document, ('version', 'operation', *OPTIONS, 'metadata'), '$')
    if document.get('version') != VERSION:
        fail('UNSUPPORTED_VERSION', 'expected ' + VERSION)
    operation = document.get('operation')
    if not isinstance(operation, str) or operation not in OPERATIONS:
        fail('UNKNOWN_FILTER', 'select encodeLossless or decodePCM16', '$.operation')
    if 'metadata' in document and operation != 'encodeLossless':
        fail('UNKNOWN_ARGUMENT', 'recording labels are an encodeLossless option; decodePCM16 drops tags and has no metadata', '$.metadata', keys=['metadata'])
    prepared = validate_arguments(OPTIONS, {k: v for k, v in document.items() if k in OPTIONS})
    source = prepared['source']
    if '\0' in source or not Path(source).is_absolute() or Path(source).suffix.lower() != SUFFIX[operation]:
        fail('INVALID_FLAC_SOURCE', 'select an absolute local regular %s file; no URLs, prefixes or relative paths' % SUFFIX[operation], '$.source')
    authored = labels(document.get('metadata')) if 'metadata' in document else None
    native = {'arguments': encode_arguments(authored) if operation == 'encodeLossless' else DECODE_ARGUMENTS,
              'pcmBridge': 'raw signed 16-bit little-endian interleaved',
              'metadata': 'none' if authored is None else {'mode': 'authoredLabels', 'encoding': 'UTF-8 bytes as authored (--no-utf8-convert)',
                                                           'comments': [line.decode('utf-8') for line in comment_lines(authored)]}}
    extra = {} if authored is None else {'metadata': authored}
    return {'version': PLAN_VERSION, 'operation': operation, **prepared, **extra, 'native': native,
            'budget': {'maxSeconds': MAX_SECONDS, 'maxPcmBytes': MAX_PCM_BYTES, 'maxWavBytes': MAX_WAV_BYTES, 'maxFlacBytes': MAX_FLAC_BYTES,
                       'rates': [RATE_MIN, RATE_MAX], 'channels': [1, 2], 'bitsPerSample': 16},
            'losses': LOSSES if authored is None else LABELLED_LOSSES}


def schema():
    from schemaxis.schema import DRAFT, argument_schema, object_schema
    def branch(name):
        return object_schema({'version': {'const': VERSION}, 'operation': {'const': name},
                              **{k: argument_schema(v) for k, v in OPTIONS.items()}}, ['version', 'operation', 'source'])
    encode, decode = branch('encodeLossless'), branch('decodePCM16')
    encode['properties']['metadata'] = {**object_schema({key: {'type': 'string', 'minLength': 1, 'maxLength': chars} for key, _, chars, _ in LABEL_FIELDS}), 'minProperties': 1}
    properties = {**encode['properties'], 'operation': {'enum': list(OPERATIONS)}}
    return {'$schema': DRAFT, **object_schema(properties, ['version', 'operation', 'source']), 'oneOf': [encode, decode]}


def query(document):
    return [plan(document)['operation']], {}


def resources(document, execution, identity):
    if execution.get('threads', 1) != 1:
        fail('INVALID_EXECUTION', 'FLAC publication supports one serial thread', identity)
    return {'threads': 1}


# ---------------------------------------------------------------- bounded host inputs and strict JSON
def bounded(path, code='VERIFICATION_FAILED', limit=MAX_FLAC_BYTES, location=None):
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


def md5(data):
    try:
        return hashlib.md5(data, usedforsecurity=False).hexdigest()
    except ValueError:
        fail('UNSUPPORTED_PLATFORM', 'FLAC STREAMINFO checksums need MD5, which this Python build disables')


def digest(directory, name, limit=MAX_FLAC_BYTES, held=None):
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
        if text.startswith('﻿'):
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


# ---------------------------------------------------------------- independent WAV reader and writer
def check_budget(frames, rate, channels, location):
    if frames > MAX_SECONDS * rate:
        fail('FLAC_BUDGET', 'audio is %.1f seconds; at most %d seconds are supported' % (frames / rate, MAX_SECONDS), location)
    if frames * channels * 2 > MAX_PCM_BYTES:
        fail('FLAC_BUDGET', 'decoded PCM is %d bytes; at most %d (a 32 MiB canonical WAV) are supported' % (frames * channels * 2, MAX_PCM_BYTES), location)


def parse_wav(data, location='$.source'):
    """Strict RIFF/WAVE reader for PCM16 mono/stereo: only fmt, data, LIST and JUNK, a 16-byte fmt chunk and exact framing.

    Parsed with ``struct`` and cross-checked against the standard ``wave`` module; no adaptor or core WAV utility is used.
    """
    def refuse(message):
        fail('INVALID_FLAC_WAV', 'use a bounded PCM16 mono or stereo WAV (8000-192000 Hz): ' + message, location)
    if len(data) > MAX_WAV_BYTES:
        fail('FLAC_BUDGET', 'WAV is larger than %d bytes' % MAX_WAV_BYTES, location)
    try:
        if len(data) < WAV_HEADER or data[:4] != b'RIFF' or data[8:12] != b'WAVE' or struct.unpack_from('<I', data, 4)[0] + 8 != len(data):
            refuse('RIFF/WAVE header or size differs from the file length')
        chunks, order, offset = {}, [], 12
        while offset < len(data):
            if offset + 8 > len(data):
                refuse('truncated chunk header')
            name, size = data[offset:offset + 4], struct.unpack_from('<I', data, offset + 4)[0]
            end = offset + 8 + size
            if end + (size & 1) > len(data) or name in chunks:
                refuse('duplicate or truncated chunk')
            if name not in (b'fmt ', b'data', b'LIST', b'JUNK'):
                refuse('unsupported chunk %r' % name)
            if size & 1 and data[end:end + 1] != b'\0':
                refuse('nonzero chunk padding byte')
            chunks[name] = (offset + 8, size)
            order.append(name)
            offset = end + (size & 1)
        if b'fmt ' not in chunks or b'data' not in chunks:
            refuse('fmt and data chunks are required')
        if order.index(b'fmt ') > order.index(b'data'):
            refuse('fmt chunk must precede data')
        if chunks[b'fmt '][1] != 16:
            refuse('a 16-byte PCM fmt chunk is required')
        encoding, channels, rate, byte_rate, align, bits = struct.unpack_from('<HHIIHH', data, chunks[b'fmt '][0])
        if encoding != 1 or bits != 16 or channels not in (1, 2) or not RATE_MIN <= rate <= RATE_MAX or align != 2 * channels or byte_rate != rate * align:
            refuse('require PCM16 mono or stereo with a consistent format and rate')
        start, size = chunks[b'data']
        if not size or size % align:
            refuse('nonempty whole sample frames are required')
        frames = size // align
        check_budget(frames, rate, channels, location)
        with wave.open(io.BytesIO(data), 'rb') as stream:
            if (stream.getnframes(), stream.getframerate(), stream.getnchannels(), stream.getsampwidth()) != (frames, rate, channels, 2):
                refuse('the standard wave module reads different geometry')
        return {'rate': rate, 'channels': channels, 'frames': frames, 'pcm': data[start:start + size],
                'droppedChunks': [name.decode('ascii') for name in order if name in (b'LIST', b'JUNK')]}
    except (struct.error, wave.Error, EOFError) as error:
        refuse(str(error))


def canonical_wav(rate, channels, pcm):
    align = 2 * channels
    return (b'RIFF' + struct.pack('<I', 36 + len(pcm)) + b'WAVEfmt ' + struct.pack('<IHHIIHH', 16, 1, channels, rate, rate * align, align, 16)
            + b'data' + struct.pack('<I', len(pcm)) + pcm)


def pcm_peaks(pcm, channels):
    samples = array('h')
    samples.frombytes(pcm)
    if sys.byteorder == 'big':
        samples.byteswap()
    return [min(samples[c::channels]) for c in range(channels)], [max(samples[c::channels]) for c in range(channels)]


def first_difference(actual, expected, channels):
    """Frame and channel of the first differing PCM byte (only called when the samples already differ)."""
    for index in range(min(len(actual), len(expected))):
        if actual[index] != expected[index]:
            return 'first difference at frame %d channel %d' % (index // (2 * channels), (index // 2) % channels)
    return 'lengths differ (%d and %d bytes)' % (len(actual), len(expected))


# ---------------------------------------------------------------- FLAC container checks (framing only; no decoder)
def crc8(data):
    value = 0
    for byte in data:
        value ^= byte
        for _ in range(8):
            value = ((value << 1) ^ 0x07) & 0xff if value & 0x80 else (value << 1) & 0xff
    return value


def read_comments(body):
    """Vendor and comment entries of a VORBIS_COMMENT block body (little-endian lengths, exact consumption), or ``None`` if malformed."""
    try:
        length = struct.unpack_from('<I', body, 0)[0]
        vendor, offset = body[4:4 + length], 4 + length
        if len(vendor) != length:
            return None
        count = struct.unpack_from('<I', body, offset)[0]
        offset += 4
        lines = []
        for _ in range(count):
            size = struct.unpack_from('<I', body, offset)[0]
            line = body[offset + 4:offset + 4 + size]
            if len(line) != size:
                return None
            lines.append(line)
            offset += 4 + size
    except struct.error:
        return None
    return (vendor, lines) if offset == len(body) else None


def parse_flac(data, location='$.source', encoder_output=False, authored=None):
    """STREAMINFO, metadata framing and the first frame header of a native FLAC file; frame bodies are never interpreted.

    Structural defects are INVALID_FLAC_STREAM, well-formed streams outside the supported subset are UNSUPPORTED_FLAC_FORMAT
    and budget overruns are FLAC_BUDGET, all before any native process starts. ``encoder_output`` additionally requires the
    exact metadata libFLAC writes for this adaptor's fixed encode: STREAMINFO then a VORBIS_COMMENT that is empty, or, when
    ``authored`` labels are given, carries exactly those fixed-field entries in fixed order, parsed from the actual bytes.
    """
    def invalid(message):
        fail('INVALID_FLAC_STREAM', 'not a well-formed native FLAC stream: ' + message, location)

    def unsupported(message):
        fail('UNSUPPORTED_FLAC_FORMAT', message, location)
    if len(data) > MAX_FLAC_BYTES:
        fail('FLAC_BUDGET', 'FLAC file is larger than %d bytes' % MAX_FLAC_BYTES, location)
    if data[:4] == b'OggS':
        unsupported('Ogg FLAC is not supported; use a native FLAC file starting with fLaC')
    if data[:3] == b'ID3':
        unsupported('an ID3v2 prefix is not supported; remove it so the file starts with fLaC')
    if data[:4] != b'fLaC':
        invalid('missing the fLaC marker at byte 0')
    offset, blocks, seen = 4, [], set()
    while True:
        if offset + 4 > len(data):
            invalid('truncated metadata block header')
        last, kind, size = data[offset] >> 7, data[offset] & 0x7f, int.from_bytes(data[offset + 1:offset + 4], 'big')
        if kind == 127:
            invalid('forbidden metadata block type 127')
        if kind not in BLOCK_TYPES:
            invalid('reserved metadata block type %d' % kind)
        if (kind == 0) != (not blocks) or (kind == 0 and size != 34):
            invalid('STREAMINFO (34 bytes) must be the first block and appear exactly once')
        if kind in (3, 4) and kind in seen:
            invalid('more than one %s block' % BLOCK_TYPES[kind])
        seen.add(kind)
        body = offset + 4
        if body + size > len(data):
            invalid('metadata block %s extends beyond the file' % BLOCK_TYPES[kind])
        blocks.append({'type': BLOCK_TYPES[kind], 'bytes': size, 'offset': body})
        offset = body + size
        if offset - 4 > MAX_METADATA_BYTES:
            fail('FLAC_BUDGET', 'metadata exceeds %d bytes' % MAX_METADATA_BYTES, location)
        if last:
            break
    raw = data[8:42]
    min_block, max_block = struct.unpack_from('>HH', raw, 0)
    min_frame, max_frame = int.from_bytes(raw[4:7], 'big'), int.from_bytes(raw[7:10], 'big')
    packed = int.from_bytes(raw[10:18], 'big')
    rate, channels, bits, total = packed >> 44, ((packed >> 41) & 7) + 1, ((packed >> 36) & 31) + 1, packed & 0xfffffffff
    digest_bytes = raw[18:34]
    if not 16 <= min_block <= max_block <= 65535:
        invalid('STREAMINFO block sizes %d and %d are outside 16-65535 or reversed' % (min_block, max_block))
    if min_frame and max_frame and min_frame > max_frame:
        invalid('STREAMINFO minimum frame size exceeds the maximum')
    if rate == 0:
        invalid('STREAMINFO sample rate is zero')
    if bits != 16:
        unsupported('%d-bit audio is not supported; only 16-bit PCM' % bits)
    if channels > 2:
        unsupported('%d channels are not supported; only mono and stereo' % channels)
    if not RATE_MIN <= rate <= RATE_MAX:
        unsupported('sample rate %d Hz is outside %d-%d Hz' % (rate, RATE_MIN, RATE_MAX))
    if total == 0:
        unsupported('the total sample count is unknown (zero); re-encode with a known length')
    if digest_bytes == bytes(16):
        unsupported('STREAMINFO carries no MD5 checksum (all zero); re-encode so the decoded samples can be checked')
    check_budget(total, rate, channels, location)
    info = {'minBlockSize': min_block, 'maxBlockSize': max_block, 'minFrameSize': min_frame, 'maxFrameSize': max_frame,
            'sampleRate': rate, 'channels': channels, 'bitsPerSample': bits, 'totalSamples': total, 'md5': digest_bytes.hex()}
    first_frame(data, offset, info, location)
    vendor, comments = None, []
    if encoder_output:
        types = [block['type'] for block in blocks]
        comment = next((b for b in blocks if b['type'] == 'VORBIS_COMMENT'), None)
        read = read_comments(data[comment['offset']:comment['offset'] + comment['bytes']]) if types == ['STREAMINFO', 'VORBIS_COMMENT'] else None
        if read is None or not VENDOR.fullmatch(read[0]):
            invalid('published FLAC metadata is not STREAMINFO plus %s libFLAC VORBIS_COMMENT' % ('an empty' if authored is None else 'a well-formed'))
        if read[1] != comment_lines(authored):
            invalid('published FLAC VORBIS_COMMENT %s' % ('is not empty' if authored is None else
                                                          'entries, values, order or count differ from the authored labels (expected %s)' % ', '.join(
                                                              field for key, field, _, _ in LABEL_FIELDS if key in authored)))
        vendor, comments = read[0].decode('ascii'), [line.decode('utf-8') for line in read[1]]
    return {'streaminfo': info, 'metadata': [{'type': b['type'], 'bytes': b['bytes']} for b in blocks], 'audioOffset': offset, 'vendor': vendor,
            'comments': comments}


def first_frame(data, offset, info, location):
    """Sync, reserved bits, header CRC-8 and agreement of the first frame header with STREAMINFO (RFC 9639 section 9.1)."""
    def invalid(message):
        fail('INVALID_FLAC_STREAM', 'not a well-formed native FLAC stream: first frame ' + message, location)
    header = data[offset:offset + 16]
    if len(header) < 6 or header[0] != 0xff or header[1] not in (0xf8, 0xf9):
        invalid('does not start with a frame sync code')
    size_code, rate_code, channel_code, depth_code, reserved = header[2] >> 4, header[2] & 15, header[3] >> 4, (header[3] >> 1) & 7, header[3] & 1
    if size_code == 0 or rate_code == 15 or channel_code > 10 or depth_code == 3 or reserved:
        invalid('uses a reserved or forbidden header value')
    if header[4] != 0:
        invalid('is not numbered zero')
    position = 5
    try:
        if size_code in (6, 7):
            width = 1 if size_code == 6 else 2
            size = int.from_bytes(header[position:position + width], 'big') + 1
            position += width
            if len(header[position - width:position]) != width or size == 65536:
                invalid('has an invalid block size')
        else:
            size = BLOCK_SIZES[size_code]
        if rate_code in RATE_CODES:
            rate = RATE_CODES[rate_code]
        elif rate_code == 0:
            rate = info['sampleRate']
        else:
            width = 1 if rate_code == 12 else 2
            value = int.from_bytes(header[position:position + width], 'big')
            position += width
            rate = value * 1000 if rate_code == 12 else value * 10 if rate_code == 14 else value
        crc = header[position]
    except (IndexError, KeyError):
        invalid('header is truncated')
    if crc8(header[:position]) != crc:
        invalid('header CRC-8 differs')
    if rate != info['sampleRate']:
        invalid('sample rate %d differs from STREAMINFO %d' % (rate, info['sampleRate']))
    if depth_code not in (0, 4):
        invalid('bit depth differs from STREAMINFO')
    if (channel_code == 0) != (info['channels'] == 1) or (channel_code != 0 and channel_code not in (1, 8, 9, 10)):
        invalid('channel assignment differs from STREAMINFO')
    if size > info['maxBlockSize'] or size > info['totalSamples'] or (size < info['minBlockSize'] and size != info['totalSamples']):
        invalid('block size %d is inconsistent with STREAMINFO' % size)
    return {'blockSize': size}


# ---------------------------------------------------------------- trusted runtime and fixed native stages
def runtime(executable=None):
    """Trusted ``flac``: explicit argument, then invocation context/stored configuration, then SCHEMAXIS_FLAC. Never PATH or a receipt."""
    value = executable or configured_executable('flac') or os.environ.get('SCHEMAXIS_FLAC')
    if not isinstance(value, str) or not os.path.isabs(value) or not os.path.isfile(value) or not os.access(value, os.X_OK):
        fail('INTERPRETER_NOT_FOUND', 'configure an absolute FLAC 1.5 flac executable; verification re-decodes the published bytes natively because no host FLAC decoder exists',
             '$.runtime.flac', recovery='use --flac, schemaxis configure flac, or SCHEMAXIS_FLAC (a stored locations.flac entry also works); schemaxis verify takes no --flac flag')
    return {'flac': value}


def launcher(stage, names, command, limit):
    """Fixed trusted launcher: resource caps, bounded input binding, minimal environment, then exec."""
    return ('import hashlib,json,os,stat,resource\nfrom pathlib import Path\n'
            'resource.setrlimit(resource.RLIMIT_AS,(2147483648,2147483648))\n'
            'resource.setrlimit(resource.RLIMIT_FSIZE,(%d,%d))\n' % (limit, limit)
            + 'resource.setrlimit(resource.RLIMIT_CPU,(%d,%d))\n' % (STAGE_TIMEOUT, STAGE_TIMEOUT)
            + 'names=%r\ncommand=%r\nbindings={}\n' % (list(names), list(command))
            + 'for name in names:\n'
            '    fd=os.open(name,os.O_RDONLY|getattr(os,"O_NOFOLLOW",0)|getattr(os,"O_NONBLOCK",0))\n'
            '    with os.fdopen(fd,"rb") as stream:\n'
            '        info=os.fstat(stream.fileno())\n'
            '        if not stat.S_ISREG(info.st_mode) or info.st_size>%d: raise ValueError("invalid native input")\n' % MAX_FLAC_BYTES
            + '        data=stream.read(%d)\n' % (MAX_FLAC_BYTES + 1)
            + '    bindings[name]=hashlib.sha256(data).hexdigest()\n'
            + 'Path(%r).write_text(json.dumps(bindings,sort_keys=True))\n' % (stage + '-inputs.json')
            + 'os.execve(command[0],command,{"LANG":"C","LC_ALL":"C"})\n')


def decode_command(flac, source, output):
    return [flac, *DECODE_ARGUMENTS, '-o', output, source]


def authored_labels(prepared):
    return prepared.get('metadata')


def stage_commands(prepared, flac, rate=0, channels=0, pcm_bytes=0):
    """Stage name -> (argument array, bound input names, native output byte limit)."""
    limit = pcm_bytes + OUTPUT_SLACK
    if prepared['operation'] == 'encodeLossless':
        return {'version': ([flac, '--version'], [], OUTPUT_SLACK),
                'encode': ([flac, *encode_arguments(authored_labels(prepared)), '--channels=%d' % channels, '--sample-rate=%d' % rate, '-o', 'audio.flac', 'source.pcm'], ['source.pcm'], limit),
                'decode': (decode_command(flac, 'audio.flac', 'reopened.pcm'), ['audio.flac'], limit)}
    return {'version': ([flac, '--version'], [], OUTPUT_SLACK),
            'decode': (decode_command(flac, 'captured.flac', 'decoded.pcm'), ['captured.flac'], limit)}


def launch(directory, stage, command, names, limit):
    """One native stage through the shared cancellable runner; every launch consults the cumulative budget."""
    directory = Path(directory)
    path = directory / (stage + '-launcher.py')
    path.write_text(launcher(stage, names, command, limit), encoding='utf-8')
    try:
        execute([sys.executable, str(path)], directory, stage, remaining_timeout(STAGE_TIMEOUT), {'LANG': 'C.UTF-8', 'PYTHONUTF8': '1'})
    except SchemaxisError as error:
        if error.fault.code != 'RUNNER_FAILED':
            raise
        target = directory / (stage + '.stderr')
        text = bounded(target, 'NATIVE_EXECUTION_FAILED', MAX_LOG_BYTES).decode('utf-8', 'replace').strip()[-300:] if target.exists() else ''
        fail('NATIVE_EXECUTION_FAILED', '%s failed (exit %s): %s' % (Path(command[0]).name, error.fault.observed.get('exitCode'), text), stage)
    return bounded(directory / (stage + '.stdout'), 'NATIVE_EXECUTION_FAILED', MAX_LOG_BYTES).decode('utf-8', 'replace')


def check_identity(text):
    if not IDENTITY.fullmatch(text):
        fail('UNSUPPORTED_RUNTIME', 'require an observed FLAC 1.5 flac (observed %r); other releases need upstream acceptance' % text[:60], 'version')
    return text.strip()


def fresh_decode(paths, flac, name, output, expected):
    """Decode the exact FLAC bytes with the trusted flac in a private directory; returns the raw PCM and the decoder identity."""
    with tempfile.TemporaryDirectory(prefix='schemaxis-flac-') as scratch:
        scratch = Path(scratch)
        (scratch / name).write_bytes(flac)
        identity = check_identity(launch(scratch, 'version', [paths['flac'], '--version'], [], OUTPUT_SLACK))
        try:
            launch(scratch, 'decode', decode_command(paths['flac'], name, output), [name], expected + OUTPUT_SLACK)
        except SchemaxisError as error:
            if error.fault.code != 'NATIVE_EXECUTION_FAILED':
                raise    # unavailable, version, timeout and cancellation faults keep their own codes
            fail('VERIFICATION_FAILED', 'FLAC bytes do not decode natively: ' + error.fault.message, name, cause=error.fault.to_dict())
        pcm = bounded(scratch / output, 'VERIFICATION_FAILED', expected + OUTPUT_SLACK)
    if len(pcm) != expected:
        fail('VERIFICATION_FAILED', 'native decode produced %d PCM bytes but STREAMINFO and the audio geometry require %d' % (len(pcm), expected))
    return pcm, identity


# ---------------------------------------------------------------- summaries, receipts and evidence
def geometry(info):
    frames = info['totalSamples']
    return {'sampleRate': info['sampleRate'], 'channels': info['channels'], 'bitsPerSample': 16, 'frames': frames,
            'durationSeconds': frames / info['sampleRate']}


def pcm_record(pcm, channels):
    low, high = pcm_peaks(pcm, channels)
    return {'bytes': len(pcm), 'sha256': sha(pcm), 'md5': md5(pcm), 'peakMin': low, 'peakMax': high}


def label_record(parsed):
    """Closed record of the labels as the host read them back from the published VORBIS_COMMENT bytes."""
    comment = next(b for b in parsed['metadata'] if b['type'] == 'VORBIS_COMMENT')
    return {'mode': 'authoredLabels', 'declaredBy': 'author', 'vorbisCommentBytes': comment['bytes'],
            'comments': [{'field': line.split('=', 1)[0], 'value': line.split('=', 1)[1], 'utf8Bytes': len(line.split('=', 1)[1].encode('utf-8'))} for line in parsed['comments']],
            'meaning': 'Author-declared labels stored exactly as authored; not an identity, rights or provenance certificate.'}


def summarize(operation, capture, parsed, pcm, published, extra, authored=None):
    info = parsed['streaminfo']
    record = {'version': SUMMARY_VERSION, 'operation': operation, 'audio': geometry(info), 'pcm': pcm_record(pcm, info['channels'])}
    if operation == 'encodeLossless':
        record['source'] = {'file': 'captured.wav', 'format': 'WAV PCM16', 'bytes': len(capture), 'sha256': sha(capture), 'droppedChunks': extra['dropped']}
        record['flac'] = {'file': 'audio.flac', 'bytes': len(published), 'sha256': sha(published), 'streaminfo': info,
                          'metadataBlocks': parsed['metadata'], 'vendor': parsed['vendor']}
        record['readback'] = {'decoder': 'flac -d (raw PCM)', 'exactPcm': True, 'pcmSha256': sha(pcm)}
        record['verification'] = ('Every PCM byte of a fresh native flac decode of the published FLAC equals the PCM of the captured WAV, and the decoded samples '
                                  'reproduce the STREAMINFO MD5 and sample count. No independent host FLAC decoder.')
        if authored:
            record['metadata'] = label_record(parsed)
            record['verification'] += (' The host parsed the published VORBIS_COMMENT bytes and found exactly the authored labels in fixed order; '
                                       'they are declared text, not a verified identity.')
    else:
        record['source'] = {'file': 'captured.flac', 'format': 'FLAC', 'bytes': len(capture), 'sha256': sha(capture), 'streaminfo': info,
                            'metadataBlocks': parsed['metadata'], 'droppedMetadataBlocks': [b['type'] for b in parsed['metadata'][1:]]}
        record['wav'] = {'file': 'audio.wav', 'format': 'canonical 44-byte PCM16 WAV', 'bytes': len(published), 'sha256': sha(published)}
        record['readback'] = {'decoder': 'flac -d (raw PCM)', 'streaminfoMd5Matches': True, 'streaminfoSampleCountMatches': True, 'pcmSha256': sha(pcm)}
        record['verification'] = ('A fresh native flac decode of the captured FLAC, whose PCM equals the published WAV payload byte for byte, reproduces the STREAMINFO MD5 and '
                                  'sample count. This is internal consistency only; it does not certify that the recording is authentic or unaltered. No independent host FLAC decoder.')
    return record


def publications(directory, operation, held=None):
    names = (('audio.flac', 'file'), ('flac-summary.json', 'text')) if operation == 'encodeLossless' else (('audio.wav', 'file'), ('flac-summary.json', 'text'))
    return [{'file': str(Path(directory) / name), 'kind': kind, 'sha256': digest(directory, name, held=held)} for name, kind in names]


def evidence_names(operation):
    names = {'authored.json', 'plan.json', 'captures.json'}
    stages = ('version', 'encode', 'decode') if operation == 'encodeLossless' else ('version', 'decode')
    names |= {'captured.wav', 'source.pcm', 'reopened.pcm'} if operation == 'encodeLossless' else {'captured.flac', 'decoded.pcm'}
    for stage in stages:
        names.update(stage + suffix for suffix in ('-launcher.py', '-inputs.json', '-submission.json', '.stdout', '.stderr'))
    return names


def unreferenced(directory, operation):
    """Exact top-level membership, including only declared framework sidecars."""
    published = ['audio.flac' if operation == 'encodeLossless' else 'audio.wav', 'flac-summary.json']
    known = evidence_names(operation) | {'verification.json', 'result.json', 'schema.snapshot.json', 'publication-metadata.json', 'job.json',
                                         *published, *[name + '.metadata.json' for name in published]}
    extra = []
    for path in Path(directory).iterdir():
        if path.name == '.dispatch':
            if path.is_symlink() or not path.is_dir():
                extra.append(path.name)
        elif path.name not in known or path.is_symlink() or not path.is_file():
            extra.append(path.name)
    return sorted(extra)


def capture_record(prepared, capture):
    record = {'source': prepared['source'], 'bytes': len(capture), 'sha256': sha(capture)}
    if authored_labels(prepared):
        record['metadata'] = authored_labels(prepared)
    return record


def audio_facts(operation, capture, location='captured'):
    """Independent host facts about the captured input: geometry, expected PCM (encode) and parsed STREAMINFO (decode)."""
    if operation == 'encodeLossless':
        wav = parse_wav(capture, location)
        return {'rate': wav['rate'], 'channels': wav['channels'], 'frames': wav['frames'], 'pcm': wav['pcm'], 'dropped': wav['droppedChunks']}
    parsed = parse_flac(capture, location)
    info = parsed['streaminfo']
    return {'rate': info['sampleRate'], 'channels': info['channels'], 'frames': info['totalSamples'], 'parsed': parsed}


# ---------------------------------------------------------------- run
def run(document, directory, *, executable=None, timeout=300):
    prepared = plan(document)
    operation = prepared['operation']
    if os.name != 'posix':
        fail('UNSUPPORTED_PLATFORM', 'native resource caps require POSIX')
    if type(timeout) not in (int, float) or not math.isfinite(timeout) or not 0 < timeout <= 3600:
        fail('INVALID_ARGUMENT', 'timeout must be finite and in (0,3600]')
    paths = runtime(executable)
    directory = Path(directory).absolute()
    if directory.exists() or directory.is_symlink():
        fail('OUTPUT_EXISTS', 'select a fresh FLAC publication directory', str(directory))
    try:
        directory.mkdir(parents=True)
    except FileExistsError:
        fail('OUTPUT_EXISTS', 'select a fresh FLAC publication directory', str(directory))
    atomic_json(directory / 'authored.json', document)
    atomic_json(directory / 'plan.json', prepared)
    atomic_json(directory / 'result.json', {'status': 'incomplete', 'verified': False})
    try:
        with execution_deadline(timeout):
            capture = bounded(prepared['source'], 'INVALID_FLAC_SOURCE', MAX_WAV_BYTES if operation == 'encodeLossless' else MAX_FLAC_BYTES, '$.source')
            facts = audio_facts(operation, capture, '$.source')
            pcm_bytes = facts['frames'] * facts['channels'] * 2
            (directory / ('captured.wav' if operation == 'encodeLossless' else 'captured.flac')).write_bytes(capture)
            if operation == 'encodeLossless':
                (directory / 'source.pcm').write_bytes(facts['pcm'])
            atomic_json(directory / 'captures.json', capture_record(prepared, capture))
            commands = stage_commands(prepared, paths['flac'], facts['rate'], facts['channels'], pcm_bytes)
            check_identity(launch(directory, 'version', *commands['version']))
            for stage in [s for s in commands if s != 'version']:
                try:
                    launch(directory, stage, *commands[stage])
                except SchemaxisError as error:
                    if operation == 'decodePCM16' and error.fault.code == 'NATIVE_EXECUTION_FAILED':
                        fail('FLAC_STREAM_REJECTED', 'the native decoder rejected the FLAC stream (damaged frames, checksum or length): ' + error.fault.message,
                             '$.source', cause=error.fault.to_dict())
                    raise
            if operation == 'decodePCM16':
                decoded = bounded(directory / 'decoded.pcm', 'NATIVE_EXECUTION_FAILED', pcm_bytes + OUTPUT_SLACK)
                if len(decoded) != pcm_bytes or md5(decoded) != facts['parsed']['streaminfo']['md5']:
                    fail('FLAC_STREAM_REJECTED', 'decoded PCM (%d bytes) disagrees with the STREAMINFO sample count or MD5 checksum' % len(decoded), '$.source')
                (directory / 'audio.wav').write_bytes(canonical_wav(facts['rate'], facts['channels'], decoded))
            observation = observe(directory, prepared, paths, {})
            atomic_json(directory / 'flac-summary.json', observation['summary'])
            atomic_json(directory / 'verification.json', {
                'artifacts': publications(directory, operation), 'evidence': {n: digest(directory, n) for n in sorted(evidence_names(operation))},
                'runtime': {'flac': observation['identity']}, 'executables': paths})
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
def converted(action, location):
    """Retained inputs that no longer satisfy the admission rules are verification failures, never input faults."""
    try:
        return action()
    except SchemaxisError as error:
        if error.fault.code not in SOURCE_FAULTS:
            raise
        fail('VERIFICATION_FAILED', 'retained %s is invalid (%s): %s' % (location, error.fault.code, error.fault.message), location, cause=error.fault.to_dict())


def observe(directory, prepared, paths, held):
    """Everything the verifier concludes from the retained inputs, published bytes and one fresh native decode.

    Returns the recomputed summary, the decoder identity and the verified PCM; raises VERIFICATION_FAILED on any difference.
    """
    directory, operation = Path(directory), prepared['operation']
    name = 'captured.wav' if operation == 'encodeLossless' else 'captured.flac'
    capture = held[name] = bounded(directory / name, limit=MAX_WAV_BYTES if operation == 'encodeLossless' else MAX_FLAC_BYTES)
    if not same_json(read_json(directory, 'captures.json'), capture_record(prepared, capture)):
        fail('VERIFICATION_FAILED', 'source capture record differs from the captured bytes')
    facts = converted(lambda: audio_facts(operation, capture, name), name)
    expected_bytes = facts['frames'] * facts['channels'] * 2
    if operation == 'encodeLossless':
        if held.setdefault('source.pcm', bounded(directory / 'source.pcm', limit=MAX_PCM_BYTES)) != facts['pcm']:
            fail('VERIFICATION_FAILED', 'raw PCM bridge differs from the captured WAV samples')
        published = held['audio.flac'] = bounded(directory / 'audio.flac', limit=MAX_FLAC_BYTES)
        authored = authored_labels(prepared)
        parsed = converted(lambda: parse_flac(published, 'audio.flac', encoder_output=True, authored=authored), 'audio.flac')
        info = parsed['streaminfo']
        if (info['sampleRate'], info['channels'], info['totalSamples']) != (facts['rate'], facts['channels'], facts['frames']):
            fail('VERIFICATION_FAILED', 'published FLAC geometry or sample count differs from the captured WAV', 'audio.flac')
        if info['md5'] != md5(facts['pcm']):
            fail('VERIFICATION_FAILED', 'published FLAC STREAMINFO MD5 differs from the captured PCM', 'audio.flac')
        pcm, identity = fresh_decode(paths, published, 'audio.flac', 'reopened.pcm', expected_bytes)
        if pcm != facts['pcm']:
            fail('VERIFICATION_FAILED', 'published FLAC does not decode to the captured PCM (%s)' % first_difference(pcm, facts['pcm'], facts['channels']), 'audio.flac')
        if held.setdefault('reopened.pcm', bounded(directory / 'reopened.pcm', limit=MAX_PCM_BYTES + OUTPUT_SLACK)) != pcm:
            fail('VERIFICATION_FAILED', 'retained run readback differs from the fresh native decode')
        summary = summarize(operation, capture, parsed, pcm, published, facts, authored)
    else:
        parsed = facts['parsed']
        pcm, identity = fresh_decode(paths, capture, 'captured.flac', 'decoded.pcm', expected_bytes)
        if md5(pcm) != parsed['streaminfo']['md5']:
            fail('VERIFICATION_FAILED', 'decoded PCM does not reproduce the STREAMINFO MD5 checksum')
        if held.setdefault('decoded.pcm', bounded(directory / 'decoded.pcm', limit=MAX_PCM_BYTES + OUTPUT_SLACK)) != pcm:
            fail('VERIFICATION_FAILED', 'retained run readback differs from the fresh native decode')
        published = held['audio.wav'] = bounded(directory / 'audio.wav', limit=MAX_WAV_BYTES)
        if published != canonical_wav(facts['rate'], facts['channels'], pcm):
            fail('VERIFICATION_FAILED', 'published WAV is not the canonical PCM16 WAV of the decoded samples', 'audio.wav')
        summary = summarize(operation, capture, parsed, pcm, published, facts)
    return {'summary': summary, 'identity': identity, 'pcm': pcm, 'facts': facts, 'published': published, 'parsed': parsed}


def result_claims(result):
    """Every claim of a result record, closed: an unknown, missing, promoted or mistyped field is a difference.

    Only ``status`` (checked separately) and the text of ``runtime.freshDecoder`` are excluded, because that identity legitimately
    varies with the verifying flac; it must still be present and a FLAC 1.5 identity string.
    """
    claims = {key: value for key, value in result.items() if key != 'status'}
    runtime_record = claims.get('runtime')
    if isinstance(runtime_record, dict):
        fresh = runtime_record.get('freshDecoder')
        claims['runtime'] = {**{key: value for key, value in runtime_record.items() if key != 'freshDecoder'},
                             'freshDecoder': isinstance(fresh, str) and IDENTITY.fullmatch(fresh) is not None}
    return claims


def verify_semantic(directory, paths, require_result=True):
    """Judge the published bytes from the authored request, captured input and a fresh native decode.

    The decision is: the actual FLAC bytes (the published ``audio.flac`` for encodeLossless, the captured ``captured.flac`` for
    decodePCM16) pass the host STREAMINFO/metadata/first-frame checks, and the trusted ``flac``, run now in a separate process on
    a private copy of exactly those bytes, produces PCM the host compares byte for byte (encode: with the PCM of the captured WAV;
    decode: with the published canonical WAV) and whose MD5 and length equal STREAMINFO. Retained files are hash-bound
    consistency diagnostics: plan, capture record, raw PCM bridge, the run's own readback, launchers, input bindings and exit
    codes (never re-executed), the summary and the receipt's membership. Retained JSON is read strictly and compared by typed
    canonical form. Receipt executables are inert provenance and are never launched. There is no host FLAC decoder: for
    decodePCM16 the MD5 agreement is consistency of the file, not proof that the recording is authentic. The judgement
    covers the bytes read during this call; a writer that changes the directory afterwards is not guarded against.
    """
    directory = Path(directory).absolute()
    try:
        with execution_deadline(VERIFY_TIMEOUT):
            try:
                prepared = plan(read_json(directory, 'authored.json'))
            except SchemaxisError as error:
                fail('VERIFICATION_FAILED', 'retained authored input is invalid: ' + error.fault.message, str(directory))
            operation = prepared['operation']
            if not same_json(read_json(directory, 'plan.json'), prepared):
                fail('VERIFICATION_FAILED', 'retained plan differs from the authored input')
            recorded_result = read_json(directory, 'result.json') if require_result else None
            if require_result and (not isinstance(recorded_result, dict) or recorded_result.get('status') != 'succeeded'):
                fail('INCOMPLETE_EXECUTION', 'FLAC publication did not complete')
            extra = unreferenced(directory, operation)
            if extra:
                fail('VERIFICATION_FAILED', 'unreferenced files in the publication directory: ' + ', '.join(extra[:8]))
            held = {}
            observation = observe(directory, prepared, paths, held)
            facts, summary = observation['facts'], observation['summary']
            saved = held['flac-summary.json'] = bounded(directory / 'flac-summary.json', limit=MAX_LOG_BYTES)
            if not same_json(strict_json(saved, 'flac-summary.json'), summary):
                fail('VERIFICATION_FAILED', 'retained summary differs from the recomputed observation')
            receipt = read_json(directory, 'verification.json')
            if not isinstance(receipt, dict) or not same_json(receipt.get('artifacts'), publications(directory, operation, held)):
                fail('VERIFICATION_FAILED', 'publication membership or digests differ from the receipt')
            evidence = receipt.get('evidence')
            if not isinstance(evidence, dict) or set(evidence) != evidence_names(operation):
                fail('VERIFICATION_FAILED', 'retained evidence membership differs')
            for name in sorted(evidence_names(operation)):
                if digest(directory, name, held=held) != evidence[name]:
                    fail('VERIFICATION_FAILED', 'retained evidence differs', name)
            recorded = receipt.get('executables')
            if not isinstance(recorded, dict) or set(recorded) != {'flac'} or not isinstance(recorded['flac'], str) or not os.path.isabs(recorded['flac']):
                fail('VERIFICATION_FAILED', 'receipt executable identity must be absolute provenance')
            runtimes = receipt.get('runtime')
            observed = check_identity(bounded(directory / 'version.stdout', limit=MAX_LOG_BYTES).decode('utf-8', 'replace'))
            if not isinstance(runtimes, dict) or set(runtimes) != {'flac'} or runtimes['flac'] != observed:
                fail('VERIFICATION_FAILED', 'recorded runtime identity differs from the retained version output', 'version')
            commands = stage_commands(prepared, recorded['flac'], facts['rate'], facts['channels'], facts['frames'] * facts['channels'] * 2)
            for stage, (command, names, limit) in commands.items():
                submission = read_json(directory, stage + '-submission.json')
                interpreter = submission.get('interpreter', {}).get('executable') if isinstance(submission.get('interpreter'), dict) else None
                native = submission.get('nativeCommand')
                if (not isinstance(interpreter, str) or not os.path.isabs(interpreter) or not isinstance(native, list) or len(native) != 2
                        or native[0] != interpreter or Path(native[1]).name != stage + '-launcher.py'
                        or type(submission.get('exitCode')) is not int or submission['exitCode'] != 0):
                    fail('VERIFICATION_FAILED', 'native command or completion record differs', stage)
                if bounded(directory / (stage + '-launcher.py'), limit=MAX_LOG_BYTES).decode() != launcher(stage, names, command, limit):
                    fail('VERIFICATION_FAILED', 'trusted native launcher differs', stage)
                if not same_json(read_json(directory, stage + '-inputs.json'), {name: digest(directory, name, held=held) for name in names}):
                    fail('VERIFICATION_FAILED', 'native input binding differs', stage)
                if stage != 'version' and (bounded(directory / (stage + '.stdout'), limit=MAX_LOG_BYTES) or bounded(directory / (stage + '.stderr'), limit=MAX_LOG_BYTES)):
                    fail('VERIFICATION_FAILED', 'a silent native stage logged output', stage)
            remaining_timeout(VERIFY_TIMEOUT)
            verified = {'verified': True, 'operation': operation, 'artifacts': 2,
                        'audio': {'sampleRate': facts['rate'], 'channels': facts['channels'], 'frames': facts['frames']},
                        'bytes': {'flac': len(observation['published']) if operation == 'encodeLossless' else len(held['captured.flac']),
                                  'wav': len(held['captured.wav']) if operation == 'encodeLossless' else len(observation['published'])},
                        'pcmSha256': sha(observation['pcm']),
                        'runtime': {'flac': runtimes['flac'], 'freshDecoder': observation['identity']}}
            if authored_labels(prepared):
                verified['metadata'] = {'mode': 'authoredLabels', 'labels': {line.split('=', 1)[0]: line.split('=', 1)[1] for line in observation['parsed']['comments']},
                                        'vorbisCommentBytes': label_record(observation['parsed'])['vorbisCommentBytes']}
            if require_result and not same_json(result_claims(recorded_result), result_claims(verified)):
                fail('VERIFICATION_FAILED', 'retained result claims differ from the verified observation')
            return verified
    except (OSError, ValueError, KeyError, TypeError, IndexError, AttributeError, UnicodeError, RecursionError, StopIteration, struct.error) as error:
        fail('VERIFICATION_FAILED', 'invalid retained FLAC evidence: %s %s' % (type(error).__name__, str(error)[:80]))


def reusableInputs(document):
    prepared = plan(document)
    source = prepared['source']
    data = bounded(source, 'INVALID_FLAC_SOURCE', MAX_WAV_BYTES if prepared['operation'] == 'encodeLossless' else MAX_FLAC_BYTES, '$.source')
    audio_facts(prepared['operation'], data, '$.source')
    return {source: sha(data)}


def verify(directory, require_result=True, *, executable=None):
    return verify_semantic(directory, runtime(executable), require_result)


from schemaxis.adaptor_runtime import bind as _bind_runtime
_bind_runtime(globals())
