"""Bounded offline narration draft from plain text, verified by fresh native re-synthesis.

``narrate`` turns one captured plain-text script into one synthetic PCM16 mono 22050 Hz WAV with one eSpeak NG voice: the
fixed ``en-us`` voice, or one explicitly selected from the closed ``voice`` choices (``en-us``, ``en-gb``, ``fr-fr``, ``es``).
The text is a literal string or an absolute UTF-8 ``.txt`` file or artifact; the host captures its
bytes, refuses everything outside a small plain-text profile (native control characters, ``[[...]]`` phoneme escapes,
markup, no words) and hands the trusted ``espeak-ng`` only a captured file with fixed arguments: no authored voice name or
path, variant, flag, markup, phoneme code, language detection, translation, network or playback. There is no host speech synthesizer: verification needs the separately
configured trusted ``espeak-ng``, which re-synthesises the captured text with the declared rate in a private directory.
The host then compares every PCM byte and rebuilds the canonical WAV itself with ``struct`` and ``wave``. Receipts never
supply an executable. The output is a synthetic DRAFT that a person must listen to. A document without ``voice`` keeps every
byte of the original en-us plans, launchers, summaries and receipts.
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

VERSION = 'schemaxis.espeakng/1'
OPERATIONS = ('narrate',)
PLAN_VERSION = 'schemaxis.espeakng.plan/1'
SUMMARY_VERSION = 'schemaxis.espeakng.summary/1'
MAX_CODE_POINTS = 1024
MAX_TEXT_BYTES = 8 * 1024
MAX_SECONDS = 120
MAX_WAV_BYTES = 8 * 1024 * 1024
WAV_HEADER = 44
MAX_PCM_BYTES = MAX_WAV_BYTES - WAV_HEADER
SAMPLE_RATE, CHANNELS, BITS = 22050, 1, 16
RATE_MIN, RATE_MAX, RATE_DEFAULT = 120, 240, 175
VOICE, PITCH, AMPLITUDE = 'en-us', 50, 100
MAX_LOG_BYTES = 1024 * 1024
OUTPUT_SLACK = 1024 * 1024
WAV_FILE_CAP = 16 * 1024 * 1024        # runaway-output guard only; the 120 s and 8 MiB budgets are judged on the finished file
DATA_FILE_LIMIT = 4 * 1024 * 1024
STAGE_TIMEOUT = 60
VERIFY_TIMEOUT = 180
RUNTIME_NAME = 'eSpeak NG 1.52.0'
IDENTITY = re.compile(r'eSpeak NG text-to-speech: 1\.52\.0  Data at: (/[^\n]+)\n?')
VOICE_ROW = re.compile(r'\s*\d+\s+(\S+)\s+(?:--|\d+)/[MF-]\s+(\S+)\s+(\S+)(?:\s.*)?')
EXPECTED_VOICE = {'language': 'en-us', 'name': 'English_(America)', 'file': 'gmw/en-US'}
DATA_FILES = ('phontab', 'phonindex', 'phondata', 'intonations', 'en_dict', 'lang/gmw/en-US')
BASE_DATA = ('phontab', 'phonindex', 'phondata', 'intonations')
# Closed voice profiles: the fixed ``--voices`` query, the one exact listing row and the native files the voice reads. Every NEW profile is selected
# by the fixed ``argument``, the identifier of its native voice file (``-vgmw/en``), never by its language name: espeak-ng resolves ``-v<name>`` through
# data/voices/<name>, data/lang/<name>, a voice-name or identifier-suffix match; the CLI can then fall back to SetVoiceByProperties for a language
# score, so extra voice files in
# modified data could redirect a name to a file that is neither inspected nor hashed, while ``-v<identifier>`` reads data/voices/<identifier> and then
# data/lang/<identifier>, the very file inspected and hashed (a voices/ file shadowing it is refused). The mapping is host code: an authored value never
# supplies an argument or a path. The legacy en-us keeps its original ``-ven-us`` (no ``argument``). The dictionary of each
# voice is the first ``language`` code of its voice file before the hyphen (voices.c at 1.52.0); the English dictionary is also consulted by every
# non-English voice for characters and words that name English, so it is fingerprinted with them. The legacy en-us entry is the unchanged original:
# it has no ``voiceFile``, so its gmw/en-US file is hashed with the other five and never parsed. Every NEW profile names its ``voiceFile``, which is
# inspected by ``inspect_voice_file`` from the very bytes that are hashed.
VOICE_PROFILES = {
    'en-us': {'query': '--voices=en', 'listing': EXPECTED_VOICE, 'data': DATA_FILES},
    'en-gb': {'query': '--voices=en-gb', 'listing': {'language': 'en-gb', 'name': 'English_(Great_Britain)', 'file': 'gmw/en'},
              'data': (*BASE_DATA, 'en_dict', 'lang/gmw/en'), 'voiceFile': 'lang/gmw/en', 'argument': 'gmw/en'},
    'fr-fr': {'query': '--voices=fr-fr', 'listing': {'language': 'fr-fr', 'name': 'French_(France)', 'file': 'roa/fr'},
              'data': (*BASE_DATA, 'fr_dict', 'en_dict', 'lang/roa/fr'), 'voiceFile': 'lang/roa/fr', 'argument': 'roa/fr'},
    'es': {'query': '--voices=es', 'listing': {'language': 'es', 'name': 'Spanish_(Spain)', 'file': 'roa/es'},
           'data': (*BASE_DATA, 'es_dict', 'en_dict', 'lang/roa/es'), 'voiceFile': 'lang/roa/es', 'argument': 'roa/es'}}
# Bounds of the voice-file inspection. LoadVoice reads a line into a buffer of N_PATH_HOME + 30 bytes (190 at the smallest platform setting); a longer
# line would be split by fgets and its tail read as a new attribute, so lines of VOICE_FILE_LINE_LIMIT bytes or more are refused. Native names are
# copied into 40-byte buffers (language_name, new_dictionary), so a token must have fewer than VOICE_FILE_TOKEN_LIMIT bytes.
VOICE_FILE_LINE_LIMIT = 160
VOICE_FILE_TOKEN_LIMIT = 40
NATIVE_SPACE = ' \t\n\v\f\r'    # C isspace in the C locale; a no-break space or any other character is not whitespace to the native parser
NATIVE_TOKEN = re.compile(r'[ \t\v\f\r]*([^ \t\v\f\r]+)')    # sscanf("%s"): skip whitespace, then read to the next whitespace
LANGUAGE_CODE = re.compile(r'[a-z]{2,3}(?:-[a-z0-9]+)*')
VOICE_CHOICES = tuple(VOICE_PROFILES)
STAGES = ('version', 'voices', 'narrate')
NATIVE_CODES = {0x0530: 'the synthesizer uses this code point internally for emphasis', 0x0557: 'the synthesizer uses this code point internally for comma breaks'}
REFUSED_CATEGORIES = {'Cc': 'control character', 'Cf': 'invisible format character', 'Cs': 'surrogate code point', 'Co': 'private-use character',
                      'Zl': 'line separator', 'Zp': 'paragraph separator'}
MARKUP = re.compile(r'<[/!?A-Za-z]|&#|&[A-Za-z][A-Za-z0-9]*;')
SOURCE_FAULTS = ('INVALID_ESPEAKNG_SOURCE', 'INVALID_ESPEAKNG_TEXT', 'ESPEAKNG_BUDGET', 'ESPEAKNG_OUTPUT_REJECTED', 'ESPEAKNG_SILENT_OUTPUT')
REVIEW_VOICE = ('Synthetic speech DRAFT produced by eSpeak NG from the captured text with the explicitly selected voice %s (listed as %s, file %s); it is not a human recording '
                'and nothing is translated or corrected. A person who reads the script language must read the words and listen to the sound before publishing it. '
                'Hashes and native re-synthesis show only that this WAV was derived consistently from the captured text, rate and selected voice by the trusted runtime; '
                'they certify no intelligibility, pronunciation, language or accent accuracy, translation, original speaker or accessibility.')
REVIEW = ('Synthetic speech DRAFT produced by eSpeak NG from the captured text; it is not a human recording. A person must read the words and '
          'listen to the sound before publishing it. Hashes and native re-synthesis show only that this WAV was derived consistently from the '
          'captured text, rate and fixed voice by the trusted runtime; they certify no intelligibility, pronunciation, accent or accessibility.')

OPTIONS = {'text': {'type': 'string', 'minLength': 1, 'maxLength': MAX_CODE_POINTS},
           'source': {'type': 'string', 'minLength': 1, 'maxLength': 4096},
           'rateWpm': {'type': 'integer', 'minimum': RATE_MIN, 'maximum': RATE_MAX, 'default': RATE_DEFAULT},
           'voice': {'type': 'enum', 'values': list(VOICE_CHOICES)}}    # no default: an absent voice is the unchanged legacy en-us narration
DECLARATIONS = {'narrate': {
    'native': 'espeak-ng --version; espeak-ng --voices=LANGUAGE; espeak-ng -vVOICE -sRATE -p50 -a100 -b1 -w native.wav -f captured.txt (eSpeak NG 1.52.0; '
              'VOICE is en-us by default or for the explicit en-us, and for the explicit en-gb, fr-fr or es the fixed identifier of its native voice file, gmw/en, roa/fr or '
              'roa/es, with the fixed LANGUAGE query of the selected voice); '
              'a fresh verification run repeats the same fixed commands in a private directory',
    'kinds': ['file', 'text'], 'inputs': {}, 'options': {k: {'value': v} for k, v in OPTIONS.items()}}}
LOSSES = [
    'The narration is a synthetic DRAFT: one fixed native English (United States) voice, pitch 50, amplitude 100 and an integer speaking rate of %d-%d words per minute '
    '(default %d). No other voice, language, variant, pitch, gap, punctuation or capital-letter option exists, and nothing is authored as a flag.' % (RATE_MIN, RATE_MAX, RATE_DEFAULT),
    'The script is plain UTF-8 text of at most %d Unicode code points and %d bytes, written either as a literal text string or as an absolute .txt file or artifact. '
    'Native control characters (every control code except a line feed), invisible format characters, private-use characters, line and paragraph separators, '
    '[[ and ]] phoneme escapes, SSML or other markup and text without a letter or digit are refused, never silently normalised. The synthesizer itself may still '
    'ignore characters, expand numbers and abbreviations or read symbols aloud by its own rules, so the words must be reviewed.' % (MAX_CODE_POINTS, MAX_TEXT_BYTES),
    'The output is canonical PCM16 mono %d Hz WAV with a 44-byte header, nonzero signal, at most %d seconds and %d MiB, ready for SoX conform. It is not a human '
    'recording and is not certified for intelligibility, pronunciation, accent or accessibility.' % (SAMPLE_RATE, MAX_SECONDS, MAX_WAV_BYTES // 1048576),
    'The requested voice is eSpeak NG en-us (listed as English_(America), gmw/en-US); the accent actually heard is not certified. There is no network, playback, '
    'language detection, translation, phoneme or markup input, and no authored code.',
    'Verification re-synthesises the captured text with a separately configured trusted espeak-ng 1.52.0 and compares every PCM byte; Schemaxis has no host speech '
    'synthesizer. Determinism was observed only for bounded cases, so a changed runtime build, voice data or version can legitimately fail an older proof: verify '
    'with the matching runtime and data, or run again to record a new narration. A coherently rewritten captured text is an unauthenticated trust anchor and the '
    'verification makes no claim that the captured text is the text its author intended.']
LOSSES_VOICE = [
    'The narration is a synthetic DRAFT spoken by one explicitly selected native voice (%s) with pitch 50, amplitude 100 and an integer speaking rate of %d-%d words per minute '
    '(default %d). Only these four voices are available. No other voice, variant, path, pitch, gap, punctuation or capital-letter option exists, and nothing is authored as a flag.'
    % (', '.join(VOICE_CHOICES), RATE_MIN, RATE_MAX, RATE_DEFAULT),
    LOSSES[1], LOSSES[2],
    'The requested voice label (en-us, en-gb, fr-fr or es) is the one eSpeak NG lists for that name (English_(America), English_(Great_Britain), French_(France) or Spanish_(Spain)); '
    'the accent actually heard and the correctness of the pronunciation are not certified. The script is spoken as written in the selected voice: there is no language detection, '
    'translation, correction of the script language, phoneme or markup input, network, playback or authored code, and a script in another language is read by that voice\'s own rules.',
    LOSSES[4]]


# ---------------------------------------------------------------- planning and the plain-text profile
def selected(prepared):
    """The voice a plan or authored document selects: the explicit ``voice`` or the legacy en-us default."""
    return prepared.get('voice', VOICE)


def codepoint(character):
    return 'U+%04X' % ord(character)


def check_text(text, location):
    """Refuse everything outside the plain-text profile; the text is never altered. Returns code point and line counts."""
    if not text:
        fail('INVALID_ESPEAKNG_TEXT', 'the script is empty; write at least one word', location)
    if len(text) > MAX_CODE_POINTS:
        fail('ESPEAKNG_BUDGET', 'the script has %d Unicode code points; at most %d are supported' % (len(text), MAX_CODE_POINTS), location,
             recovery='split the script into separate narrations of at most %d code points' % MAX_CODE_POINTS)
    for index, character in enumerate(text):
        if ord(character) in NATIVE_CODES:
            kind, reason = 'native-internal code point', NATIVE_CODES[ord(character)]
        elif character != '\n' and unicodedata.category(character) in REFUSED_CATEGORIES:
            kind = REFUSED_CATEGORIES[unicodedata.category(character)]
            reason = 'it is not plain speakable text'
        else:
            continue
        fail('INVALID_ESPEAKNG_TEXT', 'unsupported %s %s at code point index %d: %s' % (kind, codepoint(character), index, reason), location, index=index,
             recovery='remove it; control characters other than a line feed, invisible format characters, private-use characters, line and paragraph separators and the two internal code points are refused (use LF line endings, no tabs or byte-order mark)')
    for marker, label in (('[[', 'phoneme escape [['), (']]', 'phoneme escape ]]')):
        if marker in text:
            fail('INVALID_ESPEAKNG_TEXT', 'unsupported %s at code point index %d: phoneme code is not part of the plain-text profile' % (label, text.index(marker)), location,
                 index=text.index(marker), recovery='write the words themselves; phoneme escapes and phoneme mnemonics are not supported')
    markup = MARKUP.search(text)
    if markup:
        fail('INVALID_ESPEAKNG_TEXT', 'unsupported markup %r at code point index %d: SSML and other markup are not part of the plain-text profile' % (text[markup.start():markup.start() + 12], markup.start()), location,
             index=markup.start(), recovery='remove tags and character references and write plain words')
    if not any(unicodedata.category(character)[0] in 'LN' for character in text):
        fail('INVALID_ESPEAKNG_TEXT', 'the script has no letter or digit, so there is nothing to narrate', location, recovery='write at least one word')
    if len(text.encode('utf-8')) > MAX_TEXT_BYTES:
        fail('ESPEAKNG_BUDGET', 'the script is %d UTF-8 bytes; at most %d are supported' % (len(text.encode('utf-8')), MAX_TEXT_BYTES), location,
             recovery='shorten the script')
    return {'codePoints': len(text), 'lines': text.count('\n') + (0 if text.endswith('\n') else 1)}


def decode_text(data, location):
    if len(data) > MAX_TEXT_BYTES:
        fail('ESPEAKNG_BUDGET', 'the script is %d bytes; at most %d are supported' % (len(data), MAX_TEXT_BYTES), location, recovery='shorten the script')
    try:
        return data.decode('utf-8')
    except UnicodeDecodeError as error:
        fail('INVALID_ESPEAKNG_TEXT', 'the script is not valid UTF-8 (byte offset %d); re-save it as UTF-8 without a byte-order mark' % error.start, location)


def text_facts(data, location):
    text = decode_text(data, location)
    return {'bytes': len(data), **check_text(text, location)}


def plan(document):
    keys(document, ('version', 'operation', *OPTIONS), '$')
    if document.get('version') != VERSION:
        fail('UNSUPPORTED_VERSION', 'expected ' + VERSION)
    operation = document.get('operation')
    if not isinstance(operation, str) or operation not in OPERATIONS:
        fail('UNKNOWN_FILTER', 'select narrate', '$.operation')
    supplied = [name for name in ('text', 'source') if name in document]
    if len(supplied) != 1:
        fail('INVALID_ESPEAKNG_SOURCE', 'author exactly one of text (a literal script) or source (an absolute .txt file or artifact); %s supplied' % (', '.join(supplied) or 'neither was'), '$',
             recovery='keep either text or source and remove the other')
    if isinstance(document.get('text'), str):
        check_text(document['text'], '$.text')
    prepared = validate_arguments(OPTIONS, {k: v for k, v in document.items() if k in OPTIONS})
    if 'source' in prepared:
        source = prepared['source']
        if '\0' in source or not Path(source).is_absolute() or Path(source).suffix.lower() != '.txt':
            fail('INVALID_ESPEAKNG_SOURCE', 'select an absolute local regular .txt file or artifact; no URLs, prefixes or relative paths', '$.source')
    voice = selected(prepared)
    native = {'arguments': narrate_arguments(prepared['rateWpm'], voice), 'voicesQuery': [VOICE_PROFILES[voice]['query']], 'voice': voice, 'pitch': PITCH, 'amplitude': AMPLITUDE,
              'rateWpm': prepared['rateWpm'], 'input': 'captured UTF-8 text file with explicit -b1', 'output': 'PCM16 mono %d Hz WAV' % SAMPLE_RATE}
    return {'version': PLAN_VERSION, 'operation': operation, **prepared, 'native': native,
            'budget': {'maxCodePoints': MAX_CODE_POINTS, 'maxTextBytes': MAX_TEXT_BYTES, 'maxSeconds': MAX_SECONDS, 'maxWavBytes': MAX_WAV_BYTES,
                       'rateWpm': [RATE_MIN, RATE_MAX], 'sampleRate': SAMPLE_RATE, 'channels': CHANNELS, 'bitsPerSample': BITS},
            'losses': LOSSES if 'voice' not in prepared else LOSSES_VOICE}


def schema():
    from schemaxis.schema import DRAFT, argument_schema, object_schema
    def branch(name):
        return object_schema({'version': {'const': VERSION}, 'operation': {'const': 'narrate'}, name: argument_schema(OPTIONS[name]),
                              'rateWpm': argument_schema(OPTIONS['rateWpm']), 'voice': argument_schema(OPTIONS['voice'])}, ['version', 'operation', name])
    literal, file = branch('text'), branch('source')
    properties = {'version': {'const': VERSION}, 'operation': {'const': 'narrate'}, **{k: argument_schema(v) for k, v in OPTIONS.items()}}
    return {'$schema': DRAFT, **object_schema(properties, ['version', 'operation']), 'oneOf': [literal, file]}


def query(document):
    return [plan(document)['operation']], {}


def resources(document, execution, identity):
    if execution.get('threads', 1) != 1:
        fail('INVALID_EXECUTION', 'narration supports one serial thread', identity)
    return {'threads': 1}


# ---------------------------------------------------------------- bounded host inputs and strict JSON
def bounded(path, code='VERIFICATION_FAILED', limit=MAX_WAV_BYTES, location=None):
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


def read_source(path, location='$.source'):
    """Bounded read of the authored script file: regular, not a symlink, at most the text budget."""
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0))
        with os.fdopen(fd, 'rb') as stream:
            info = os.fstat(stream.fileno())
            regular, size = stat.S_ISREG(info.st_mode), info.st_size
            data = stream.read(MAX_TEXT_BYTES + 1) if regular and size <= MAX_TEXT_BYTES else b''
    except OSError as error:
        fail('INVALID_ESPEAKNG_SOURCE', 'select an intact absolute regular .txt file (no symlinks): %s' % (error.strerror or error), location)
    if not regular:
        fail('INVALID_ESPEAKNG_SOURCE', 'select an intact absolute regular .txt file (no symlinks, directories or devices)', location)
    if size > MAX_TEXT_BYTES or len(data) > MAX_TEXT_BYTES:
        fail('ESPEAKNG_BUDGET', 'the script file is larger than %d bytes' % MAX_TEXT_BYTES, location, recovery='shorten the script')
    return data


def sha(data):
    return hashlib.sha256(data).hexdigest()


def digest(directory, name, limit=MAX_WAV_BYTES, held=None):
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
def canonical_wav(pcm):
    return (b'RIFF' + struct.pack('<I', 36 + len(pcm)) + b'WAVEfmt ' + struct.pack('<IHHIIHH', 16, 1, CHANNELS, SAMPLE_RATE, SAMPLE_RATE * 2, 2, BITS)
            + b'data' + struct.pack('<I', len(pcm)) + pcm)


def parse_wav(data, location='native.wav'):
    """Strict reader of the one WAV layout the adaptor accepts: canonical 44-byte header, PCM16 mono 22050 Hz, exact sizes, nonzero signal.

    Parsed with ``struct`` and cross-checked against the standard ``wave`` module; no adaptor or core WAV utility is used.
    """
    def refuse(message):
        fail('ESPEAKNG_OUTPUT_REJECTED', 'the native output is not the expected canonical PCM16 mono %d Hz WAV: %s' % (SAMPLE_RATE, message), location)
    if len(data) > MAX_WAV_BYTES:
        fail('ESPEAKNG_BUDGET', 'the narration is larger than %d bytes' % MAX_WAV_BYTES, location, recovery='shorten the script or raise rateWpm')
    if len(data) < WAV_HEADER:
        refuse('shorter than a 44-byte header')
    try:
        riff, size, kind, fmt, fmt_size, encoding, channels, rate, byte_rate, align, bits, tag, data_size = struct.unpack('<4sI4s4sIHHIIHH4sI', data[:WAV_HEADER])
    except struct.error as error:
        refuse(str(error))
    if (riff, kind, fmt, tag) != (b'RIFF', b'WAVE', b'fmt ', b'data') or fmt_size != 16:
        refuse('chunk layout is not RIFF/WAVE, a 16-byte fmt chunk and data')
    if size + 8 != len(data) or data_size != len(data) - WAV_HEADER:
        refuse('RIFF or data size differs from the file length')
    if (encoding, channels, rate, byte_rate, align, bits) != (1, CHANNELS, SAMPLE_RATE, SAMPLE_RATE * 2, 2, BITS):
        refuse('format is %d channel(s) at %d Hz, %d-bit encoding %d' % (channels, rate, bits, encoding))
    if data_size == 0 or data_size % 2:
        refuse('nonempty whole sample frames are required')
    frames = data_size // 2
    if frames > MAX_SECONDS * SAMPLE_RATE:
        fail('ESPEAKNG_BUDGET', 'the narration is %.1f seconds; at most %d seconds are supported' % (frames / SAMPLE_RATE, MAX_SECONDS), location,
             recovery='shorten the script or raise rateWpm')
    try:
        with wave.open(io.BytesIO(data), 'rb') as stream:
            if (stream.getnframes(), stream.getframerate(), stream.getnchannels(), stream.getsampwidth()) != (frames, SAMPLE_RATE, CHANNELS, 2):
                refuse('the standard wave module reads different geometry')
    except (wave.Error, EOFError) as error:
        refuse(str(error))
    pcm = data[WAV_HEADER:]
    if not any(pcm):
        fail('ESPEAKNG_SILENT_OUTPUT', 'the native synthesis produced only silence (%d zero samples)' % frames, location,
             recovery='write words the English voice can speak; punctuation, spaces and unsupported symbols can synthesise silence')
    return {'frames': frames, 'pcm': pcm}


def pcm_record(pcm):
    samples = array('h')
    samples.frombytes(pcm)
    if sys.byteorder == 'big':
        samples.byteswap()
    return {'bytes': len(pcm), 'sha256': sha(pcm), 'peakAbs': max(max(samples), -min(samples)), 'nonzeroSamples': sum(1 for sample in samples if sample)}


def first_difference(actual, expected):
    """Sample index of the first differing PCM byte (only called when the samples already differ)."""
    for index in range(min(len(actual), len(expected))):
        if actual[index] != expected[index]:
            return 'first difference at sample %d' % (index // 2)
    return 'lengths differ (%d and %d samples)' % (len(actual) // 2, len(expected) // 2)


# ---------------------------------------------------------------- trusted runtime and fixed native stages
def runtime(executable=None):
    """Trusted ``espeak-ng``: explicit argument, then invocation context/stored configuration, then SCHEMAXIS_ESPEAKNG. Never PATH or a receipt."""
    value = executable or configured_executable('espeakng') or os.environ.get('SCHEMAXIS_ESPEAKNG')
    if not isinstance(value, str) or not os.path.isabs(value) or not os.path.isfile(value) or not os.access(value, os.X_OK):
        fail('INTERPRETER_NOT_FOUND', 'configure an absolute eSpeak NG 1.52.0 espeak-ng executable; verification re-synthesises the narration natively because no host speech synthesizer exists',
             '$.runtime.espeakng', recovery='use --espeakng, schemaxis configure espeakng, or SCHEMAXIS_ESPEAKNG (a stored locations.espeakng entry also works); schemaxis verify takes no --espeakng flag')
    return {'espeakng': value}


def narrate_arguments(rate, voice=VOICE):
    return ['-v' + VOICE_PROFILES[voice].get('argument', voice), '-s%d' % rate, '-p%d' % PITCH, '-a%d' % AMPLITUDE, '-b1', '-w', 'native.wav', '-f', 'captured.txt']


def launcher(stage, names, command, limit):
    """Fixed trusted launcher: resource caps, bounded input binding, minimal environment (no HOME or data-path override), then exec."""
    return ('import hashlib,json,os,stat,resource\nfrom pathlib import Path\n'
            'resource.setrlimit(resource.RLIMIT_AS,(2147483648,2147483648))\n'
            'resource.setrlimit(resource.RLIMIT_FSIZE,(%d,%d))\n' % (limit, limit)
            + 'resource.setrlimit(resource.RLIMIT_CPU,(%d,%d))\n' % (STAGE_TIMEOUT, STAGE_TIMEOUT)
            + 'resource.setrlimit(resource.RLIMIT_CORE,(0,0))\n'
            + 'names=%r\ncommand=%r\nbindings={}\n' % (list(names), list(command))
            + 'for name in names:\n'
            '    fd=os.open(name,os.O_RDONLY|getattr(os,"O_NOFOLLOW",0)|getattr(os,"O_NONBLOCK",0))\n'
            '    with os.fdopen(fd,"rb") as stream:\n'
            '        info=os.fstat(stream.fileno())\n'
            '        if not stat.S_ISREG(info.st_mode) or info.st_size>%d: raise ValueError("invalid native input")\n' % MAX_TEXT_BYTES
            + '        data=stream.read(%d)\n' % (MAX_TEXT_BYTES + 1)
            + '    bindings[name]=hashlib.sha256(data).hexdigest()\n'
            + 'Path(%r).write_text(json.dumps(bindings,sort_keys=True))\n' % (stage + '-inputs.json')
            + 'os.execve(command[0],command,{"LANG":"C.UTF-8","LC_ALL":"C.UTF-8"})\n')


def stage_commands(rate, espeak, voice=VOICE):
    """Stage name -> (argument array, bound input names, native output byte limit)."""
    return {'version': ([espeak, '--version'], [], OUTPUT_SLACK),
            'voices': ([espeak, VOICE_PROFILES[voice]['query']], [], OUTPUT_SLACK),
            'narrate': ([espeak, *narrate_arguments(rate, voice)], ['captured.txt'], WAV_FILE_CAP)}


def launch(directory, stage, command, names, limit):
    """One native stage through the shared cancellable runner; every launch consults the cumulative budget."""
    directory = Path(directory)
    path = directory / (stage + '-launcher.py')
    path.write_text(launcher(stage, names, command, limit))
    try:
        execute([sys.executable, str(path)], directory, stage, remaining_timeout(STAGE_TIMEOUT), {'LANG': 'C.UTF-8'})
    except SchemaxisError as error:
        if error.fault.code != 'RUNNER_FAILED':
            raise
        target = directory / (stage + '.stderr')
        text = bounded(target, 'NATIVE_EXECUTION_FAILED', MAX_LOG_BYTES).decode('utf-8', 'replace').strip()[-300:] if target.exists() else ''
        fail('NATIVE_EXECUTION_FAILED', '%s failed (exit %s): %s' % (Path(command[0]).name, error.fault.observed.get('exitCode'), text), stage)
    return bounded(directory / (stage + '.stdout'), 'NATIVE_EXECUTION_FAILED', MAX_LOG_BYTES).decode('utf-8', 'replace')


def check_identity(text):
    """Observed runtime identity (public, normalised) and the private data directory the runtime announced."""
    match = IDENTITY.fullmatch(text)
    if not match:
        fail('UNSUPPORTED_RUNTIME', 'require an observed eSpeak NG 1.52.0 espeak-ng (observed %r); other releases need upstream acceptance' % text[:60], 'version')
    return RUNTIME_NAME, match.group(1)


def data_fingerprint(directory, voice=VOICE):
    """Fingerprint of the chosen native files of the selected voice (phoneme tables, its dictionary, the English fallback dictionary, its voice file).

    Not every file the runtime may read: the path stays private and the PCM comparison, not this fingerprint, decides. A new profile's voice file is
    also inspected (``inspect_voice_file``) from the same bytes that are hashed; the legacy en-us profile is only hashed. The synthesis command names that
    file by its fixed identifier, so the file read is the file inspected and hashed unless a ``voices/`` file shadows it, which is refused. The trusted native
    program is assumed not to be swapped or raced while it runs; nothing here claims filesystem race protection or closure over every native file.
    """
    root, hashes, profile = Path(directory), {}, VOICE_PROFILES[voice]
    if not root.is_absolute() or not root.is_dir():
        fail('UNSUPPORTED_RUNTIME', 'the runtime announced a native data directory that does not exist', 'version')
    for name in profile['data']:
        try:
            data = bounded(root / name, 'UNSUPPORTED_RUNTIME', DATA_FILE_LIMIT, 'version')
        except SchemaxisError as error:
            fail('UNSUPPORTED_RUNTIME', 'the runtime native data is incomplete (%s): %s' % (name, error.fault.message), 'version')
        if name == profile.get('voiceFile'):
            shadow = 'voices/' + name[len('lang/'):]
            if os.path.lexists(root / shadow):
                fail('UNSUPPORTED_RUNTIME', 'the runtime native data has %s, which LoadVoice would read instead of the inspected %s' % (shadow, name), 'version',
                     recovery='use the matching eSpeak NG 1.52.0 native data, which has no voices/ file for this voice')
            inspect_voice_file(data, name, profile['listing']['language'])
        hashes[name] = sha(data)
    return sha(json.dumps(hashes, sort_keys=True).encode())


def inspect_voice_file(data, name, language):
    """Bounded check that the voice file the runtime reads for ``language`` resolves to that language's dictionary (LoadVoice at 1.52.0).

    Follows only what LoadVoice does with ``language`` and ``dictionary`` lines: ``#`` at the start of a line blanks it, trailing whitespace is
    dropped, ``//`` truncates, the attribute is the text before the first whitespace (case-sensitive; a line starting with whitespace is ignored),
    and only the FIRST ``language`` line selects the translator and dictionary (its text before the first ``-``). Every ``language`` line must be
    well formed, the first must be exactly the listed language, and a ``dictionary`` line may only repeat the expected dictionary. Anything this
    cannot decide is refused, never guessed. No other attribute is interpreted: this is not a parser of all native voice options.
    """
    def refuse(reason, number=None):
        fail('UNSUPPORTED_RUNTIME', 'the selected voice file %s %s%s' % (name, reason, '' if number is None else ' (line %d)' % number), 'version',
             recovery='use the matching eSpeak NG 1.52.0 native data; the file must declare the %s language first and no other dictionary' % language)
    stem, first = language.split('-')[0], None
    if b'\0' in data:
        refuse('contains a NUL byte')
    for number, raw in enumerate(data.split(b'\n'), 1):
        if len(raw) >= VOICE_FILE_LINE_LIMIT:
            refuse('has a line longer than the %d bytes this check can follow' % (VOICE_FILE_LINE_LIMIT - 1), number)
        try:
            line = raw.decode('utf-8')
        except UnicodeDecodeError:
            refuse('is not valid UTF-8', number)
        if line.startswith('#'):
            continue
        line = line.rstrip(NATIVE_SPACE)
        line = line.split('//', 1)[0]
        end = next((index for index, character in enumerate(line) if character in NATIVE_SPACE), len(line))
        attribute, rest = line[:end], line[end + 1:]
        if attribute not in ('language', 'dictionary'):
            continue
        token = NATIVE_TOKEN.match(rest) if end < len(line) else None
        if not token:
            refuse('has a %s declaration without an argument, which the native parser reads past the end of the line' % attribute, number)
        value = token.group(1)
        if len(value) >= VOICE_FILE_TOKEN_LIMIT:
            refuse('has a %s name too long for the native 40-byte buffer' % attribute, number)
        if attribute == 'dictionary':
            if value != stem:
                refuse('names the %s dictionary, not the expected %s dictionary' % (value, stem), number)
            continue
        if value == 'variant':
            refuse('has a variant language declaration, which a language voice file does not have', number)
        if not LANGUAGE_CODE.fullmatch(value):
            refuse('has a malformed language code %r' % value[:40], number)
        if first is None:
            first = value
            if value.split('-')[0] != stem:
                refuse('declares the primary language %s, not %s' % (value, language), number)
            if value != language:
                refuse('declares the first language %s, not the listed %s' % (value, language), number)
    if first is None:
        refuse('declares no primary language')


def check_voice(text, voice=VOICE):
    """The selected voice must be listed, exactly once, by the fixed public voice query; eSpeak NG would otherwise fall back to another voice.

    Only the first (language) column names a voice: the Other Languages column and variants such as en-gb-x-rp never select it. A voice listed
    more than once, identically or not, is ambiguous about which voice file is read and is refused.
    """
    expected = VOICE_PROFILES[voice]['listing']
    rows = []
    for line in text.splitlines():
        match = VOICE_ROW.fullmatch(line)
        if match and match.group(1) == voice:
            rows.append({'language': match.group(1), 'name': match.group(2), 'file': match.group(3)})
    if not rows:
        fail('UNSUPPORTED_RUNTIME', 'the runtime does not list the %s voice, and eSpeak NG would silently fall back to another voice' % voice, 'voices',
             recovery='use an eSpeak NG 1.52.0 build with its matching native data')
    if len(rows) > 1:
        fail('UNSUPPORTED_RUNTIME', 'the runtime lists the %s voice %d times with %s rows, so the voice file it reads is ambiguous; exactly one row is required' % (
            voice, len(rows), 'identical' if all(row == rows[0] for row in rows) else 'conflicting'), 'voices',
             recovery='use an eSpeak NG 1.52.0 build with its matching native data')
    if rows[0] != expected:
        fail('UNSUPPORTED_RUNTIME', 'the runtime lists %s as %r, not the expected %s voice %s' % (voice, rows[0], expected['name'], expected['file']), 'voices')
    return rows[0]


def synthesize(directory, espeak, rate, voice=VOICE):
    """Run the three fixed stages on ``captured.txt`` in ``directory``; returns identity, data fingerprint, voice listing and parsed output."""
    directory = Path(directory)
    commands = stage_commands(rate, espeak, voice)
    identity, data = check_identity(launch(directory, 'version', *commands['version']))
    fingerprint = data_fingerprint(data, voice)
    listing = check_voice(launch(directory, 'voices', *commands['voices']), voice)
    try:
        launch(directory, 'narrate', *commands['narrate'])
    except SchemaxisError as error:
        produced = directory / 'native.wav'
        if error.fault.code == 'NATIVE_EXECUTION_FAILED' and produced.is_file() and produced.stat().st_size >= WAV_FILE_CAP - 4096:
            fail('ESPEAKNG_BUDGET', 'the native output reached the %d MiB runaway guard; the finished narration may not exceed %d seconds or %d MiB' % (
                WAV_FILE_CAP // 1048576, MAX_SECONDS, MAX_WAV_BYTES // 1048576), 'narrate', recovery='shorten the script or raise rateWpm')
        raise
    if bounded(directory / 'narrate.stdout', 'NATIVE_EXECUTION_FAILED', MAX_LOG_BYTES) or bounded(directory / 'narrate.stderr', 'NATIVE_EXECUTION_FAILED', MAX_LOG_BYTES):
        fail('NATIVE_EXECUTION_FAILED', 'the narration stage wrote unexpected output', 'narrate')
    produced = directory / 'native.wav'
    if not produced.is_file():
        fail('ESPEAKNG_SILENT_OUTPUT', 'the native synthesis wrote no audio', 'narrate', recovery='write words the English voice can speak')
    native = bounded(produced, 'ESPEAKNG_OUTPUT_REJECTED', WAV_FILE_CAP, 'native.wav')
    parsed = parse_wav(native, 'native.wav')
    if native != canonical_wav(parsed['pcm']):
        fail('ESPEAKNG_OUTPUT_REJECTED', 'the native WAV is not byte-identical to its canonical rebuild', 'native.wav')
    return {'identity': identity, 'dataFingerprint': fingerprint, 'voice': listing, 'native': native, **parsed}


def fresh_synthesis(espeak, capture, rate, voice=VOICE):
    """Re-synthesise the exact captured bytes with the trusted espeak-ng in a private directory outside the submitted run."""
    with tempfile.TemporaryDirectory(prefix='schemaxis-espeakng-') as scratch:
        (Path(scratch) / 'captured.txt').write_bytes(capture)
        try:
            return synthesize(scratch, espeak, rate, voice)
        except SchemaxisError as error:
            if error.fault.code == 'NATIVE_EXECUTION_FAILED' or error.fault.code in SOURCE_FAULTS:
                fail('VERIFICATION_FAILED', 'fresh native re-synthesis of the captured text failed (%s): %s' % (error.fault.code, error.fault.message), 'captured.txt', cause=error.fault.to_dict())
            raise    # unavailable, version, timeout and cancellation faults keep their own codes


# ---------------------------------------------------------------- summaries, receipts and evidence
def capture_record(prepared, capture):
    record = {'kind': 'file' if 'source' in prepared else 'literal', 'bytes': len(capture), 'sha256': sha(capture)}
    if 'source' in prepared:
        record['source'] = prepared['source']
    if 'voice' in prepared:
        record['voice'] = prepared['voice']    # only an explicit selection is recorded, so an absent voice keeps the legacy record
    return record


def review_text(prepared, listing):
    if 'voice' not in prepared:
        return REVIEW
    return REVIEW_VOICE % (prepared['voice'], listing['name'], listing['file'])


def summarize(prepared, capture, facts, parsed, published, observed):
    pcm = parsed['pcm']
    return {'version': SUMMARY_VERSION, 'operation': 'narrate',
            'source': {'kind': 'file' if 'source' in prepared else 'literal', 'file': 'captured.txt', 'bytes': len(capture), 'sha256': sha(capture),
                       'codePoints': facts['codePoints'], 'lines': facts['lines']},
            'voice': {'requested': selected(prepared), 'listing': observed['voice'], 'rateWpm': prepared['rateWpm'], 'pitch': PITCH, 'amplitude': AMPLITUDE, 'inputEncoding': 'UTF-8 (-b1)'},
            'audio': {'sampleRate': SAMPLE_RATE, 'channels': CHANNELS, 'bitsPerSample': BITS, 'frames': parsed['frames'], 'durationSeconds': parsed['frames'] / SAMPLE_RATE},
            'pcm': pcm_record(pcm),
            'wav': {'file': 'narration.wav', 'format': 'canonical 44-byte PCM16 mono %d Hz WAV' % SAMPLE_RATE, 'bytes': len(published), 'sha256': sha(published)},
            'runtime': {'identity': observed['identity'], 'dataFingerprint': observed['dataFingerprint']},
            'readback': {'method': 'fresh native re-synthesis from the captured text', 'pcmIdentical': True, 'pcmSha256': sha(pcm)},
            'review': review_text(prepared, observed['voice']),
            'verification': ('Every PCM byte of a fresh native eSpeak NG re-synthesis of the captured text at the declared rate equals the published WAV payload, and the host '
                             'rebuilt the canonical WAV itself. This is a synthetic draft: listen to it and read the words; no intelligibility, pronunciation, accent or '
                             'accessibility is certified. No host speech synthesizer; a rewritten captured text is an unauthenticated trust anchor.'
                             if 'voice' not in prepared else
                             'Every PCM byte of a fresh native eSpeak NG re-synthesis of the captured text at the declared rate and the explicitly selected voice equals the '
                             'published WAV payload, and the host rebuilt the canonical WAV itself. This is a synthetic draft: listen to it and read the words; no intelligibility, '
                             'pronunciation, language or accent accuracy, translation or accessibility is certified. No host speech synthesizer; a rewritten captured text is an '
                             'unauthenticated trust anchor.')}


def publications(directory, held=None):
    return [{'file': str(Path(directory) / name), 'kind': kind, 'sha256': digest(directory, name, held=held)}
            for name, kind in (('narration.wav', 'file'), ('espeakng-summary.json', 'text'))]


def evidence_names():
    names = {'authored.json', 'plan.json', 'captures.json', 'captured.txt', 'native.wav'}
    for stage in STAGES:
        names.update(stage + suffix for suffix in ('-launcher.py', '-inputs.json', '-submission.json', '.stdout', '.stderr'))
    return names


def unreferenced(directory):
    """Exact top-level membership, including only declared framework sidecars."""
    published = ['narration.wav', 'espeakng-summary.json']
    known = evidence_names() | {'verification.json', 'result.json', 'schema.snapshot.json', 'publication-metadata.json', 'job.json',
                                *published, *[name + '.metadata.json' for name in published]}
    extra = []
    for path in Path(directory).iterdir():
        if path.name == '.dispatch':
            if path.is_symlink() or not path.is_dir():
                extra.append(path.name)
        elif path.name not in known or path.is_symlink() or not path.is_file():
            extra.append(path.name)
    return sorted(extra)


# ---------------------------------------------------------------- run
def run(document, directory, *, executable=None, timeout=300):
    prepared = plan(document)
    if os.name != 'posix':
        fail('UNSUPPORTED_PLATFORM', 'native resource caps require POSIX')
    if type(timeout) not in (int, float) or not math.isfinite(timeout) or not 0 < timeout <= 3600:
        fail('INVALID_ARGUMENT', 'timeout must be finite and in (0,3600]')
    paths = runtime(executable)
    directory = Path(directory).absolute()
    if directory.exists() or directory.is_symlink():
        fail('OUTPUT_EXISTS', 'select a fresh narration publication directory', str(directory))
    try:
        directory.mkdir(parents=True)
    except FileExistsError:
        fail('OUTPUT_EXISTS', 'select a fresh narration publication directory', str(directory))
    atomic_json(directory / 'authored.json', document)
    atomic_json(directory / 'plan.json', prepared)
    atomic_json(directory / 'result.json', {'status': 'incomplete', 'verified': False})
    try:
        with execution_deadline(timeout):
            capture = prepared['text'].encode('utf-8') if 'text' in prepared else read_source(prepared['source'], '$.source')
            text_facts(capture, '$.text' if 'text' in prepared else '$.source')
            (directory / 'captured.txt').write_bytes(capture)
            atomic_json(directory / 'captures.json', capture_record(prepared, capture))
            made = synthesize(directory, paths['espeakng'], prepared['rateWpm'], selected(prepared))
            (directory / 'narration.wav').write_bytes(made['native'])
            observation = observe(directory, prepared, paths, {}, made)
            atomic_json(directory / 'espeakng-summary.json', observation['summary'])
            atomic_json(directory / 'verification.json', {
                'artifacts': publications(directory), 'evidence': {n: digest(directory, n) for n in sorted(evidence_names())},
                'runtime': {'espeakng': observation['identity'], 'dataFingerprint': observation['dataFingerprint']}, 'executables': paths,
                **({'voice': prepared['voice']} if 'voice' in prepared else {})})
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
        for name in ('narration.wav', 'espeakng-summary.json', 'verification.json'):    # a failed run never leaves unverified publications
            (directory / name).unlink(missing_ok=True)
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


def observe(directory, prepared, paths, held, expected):
    """Everything the verifier concludes from the retained input, the published bytes and one fresh native re-synthesis.

    ``expected`` is the runtime identity and data fingerprint the run recorded. Returns the recomputed summary and the verified
    PCM; raises VERIFICATION_FAILED on any difference.
    """
    directory = Path(directory)
    capture = held['captured.txt'] = bounded(directory / 'captured.txt', limit=MAX_TEXT_BYTES)
    if not same_json(read_json(directory, 'captures.json'), capture_record(prepared, capture)):
        fail('VERIFICATION_FAILED', 'source capture record differs from the captured bytes')
    if 'text' in prepared and capture != prepared['text'].encode('utf-8'):
        fail('VERIFICATION_FAILED', 'captured text differs from the authored literal text', 'captured.txt')
    facts = converted(lambda: text_facts(capture, 'captured.txt'), 'captured.txt')
    fresh = fresh_synthesis(paths['espeakng'], capture, prepared['rateWpm'], selected(prepared))
    native = held['native.wav'] = bounded(directory / 'native.wav', limit=MAX_WAV_BYTES)
    published = held['narration.wav'] = bounded(directory / 'narration.wav', limit=MAX_WAV_BYTES)
    retained = converted(lambda: parse_wav(native, 'native.wav'), 'native.wav')
    shipped = converted(lambda: parse_wav(published, 'narration.wav'), 'narration.wav')
    moved = (fresh['identity'], fresh['dataFingerprint']) != (expected['identity'], expected['dataFingerprint'])
    for label, parsed, name in (('published narration', shipped, 'narration.wav'), ('retained run output', retained, 'native.wav')):
        if parsed['pcm'] != fresh['pcm']:
            hint = ('; the verifying runtime or its native data differs from the recorded ones (identity %s, data %s): verify with the matching runtime and data, or run again to re-record'
                    % (fresh['identity'], fresh['dataFingerprint'][:12])) if moved else ''
            fail('VERIFICATION_FAILED', '%s does not equal fresh native re-synthesis (%s)%s' % (label, first_difference(parsed['pcm'], fresh['pcm']), hint), name)
    if moved:
        fail('VERIFICATION_FAILED', 'the verifying runtime or native data differs from the recorded runtime (identity %s, data %s) although the PCM agrees; '
             'verify with the matching runtime and data, or run again to re-record' % (fresh['identity'], fresh['dataFingerprint'][:12]), 'version')
    if published != canonical_wav(fresh['pcm']) or native != published:
        fail('VERIFICATION_FAILED', 'published WAV is not the canonical PCM16 WAV of the re-synthesised samples', 'narration.wav')
    return {'summary': summarize(prepared, capture, facts, fresh, published, fresh), 'identity': fresh['identity'], 'dataFingerprint': fresh['dataFingerprint'],
            'pcm': fresh['pcm'], 'frames': fresh['frames'], 'published': published}


def result_claims(result):
    """Every claim of a result record, closed: an unknown, missing, promoted or mistyped field is a difference; only ``status`` is checked separately."""
    return {key: value for key, value in result.items() if key != 'status'}


def verify_semantic(directory, paths, require_result=True):
    """Judge the published bytes from the authored request, captured text and a fresh native re-synthesis.

    The decision is: the captured text passes the plain-text profile, and the trusted ``espeak-ng``, run now in a separate
    process on a private copy of exactly those bytes at the declared rate, produces PCM that the host compares byte for byte with
    the published WAV, which must be the canonical PCM16 WAV the host rebuilds itself. Retained files are hash-bound consistency
    diagnostics: plan, capture record, the run's own output, launchers, input bindings and exit codes (never re-executed), the
    summary and the receipt's membership. Retained JSON is read strictly and compared by typed canonical form. Receipt
    executables are inert provenance and are never launched. There is no host speech synthesizer. The judgement covers the bytes
    read during this call; a writer that changes the directory afterwards is not guarded against, and a coherent rewrite of the
    captured text is an unauthenticated trust anchor.
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
                fail('INCOMPLETE_EXECUTION', 'narration publication did not complete')
            extra = unreferenced(directory)
            if extra:
                fail('VERIFICATION_FAILED', 'unreferenced files in the publication directory: ' + ', '.join(extra[:8]))
            receipt = read_json(directory, 'verification.json')
            runtimes = receipt.get('runtime') if isinstance(receipt, dict) else None
            if (not isinstance(runtimes, dict) or set(runtimes) != {'espeakng', 'dataFingerprint'} or runtimes['espeakng'] != RUNTIME_NAME
                    or not isinstance(runtimes['dataFingerprint'], str) or not re.fullmatch('[0-9a-f]{64}', runtimes['dataFingerprint'])):
                fail('VERIFICATION_FAILED', 'recorded runtime identity or data fingerprint is invalid', 'verification.json')
            if ('voice' in receipt) != ('voice' in prepared) or (receipt.get('voice') if 'voice' in prepared else None) != prepared.get('voice'):
                fail('VERIFICATION_FAILED', 'receipt voice claim differs from the authored voice selection', 'verification.json')
            held = {}
            observation = observe(directory, prepared, paths, held, {'identity': runtimes['espeakng'], 'dataFingerprint': runtimes['dataFingerprint']})
            saved = held['espeakng-summary.json'] = bounded(directory / 'espeakng-summary.json', limit=MAX_LOG_BYTES)
            if not same_json(strict_json(saved, 'espeakng-summary.json'), observation['summary']):
                fail('VERIFICATION_FAILED', 'retained summary differs from the recomputed observation')
            if not same_json(receipt.get('artifacts'), publications(directory, held)):
                fail('VERIFICATION_FAILED', 'publication membership or digests differ from the receipt')
            evidence = receipt.get('evidence')
            if not isinstance(evidence, dict) or set(evidence) != evidence_names():
                fail('VERIFICATION_FAILED', 'retained evidence membership differs')
            for name in sorted(evidence_names()):
                if digest(directory, name, held=held) != evidence[name]:
                    fail('VERIFICATION_FAILED', 'retained evidence differs', name)
            recorded = receipt.get('executables')
            if not isinstance(recorded, dict) or set(recorded) != {'espeakng'} or not isinstance(recorded['espeakng'], str) or not os.path.isabs(recorded['espeakng']):
                fail('VERIFICATION_FAILED', 'receipt executable identity must be absolute provenance')
            seen, _ = check_identity(bounded(directory / 'version.stdout', limit=MAX_LOG_BYTES).decode('utf-8', 'replace'))
            if seen != runtimes['espeakng']:
                fail('VERIFICATION_FAILED', 'recorded runtime identity differs from the retained version output', 'version')
            if check_voice(bounded(directory / 'voices.stdout', limit=MAX_LOG_BYTES).decode('utf-8', 'replace'), selected(prepared)) != observation['summary']['voice']['listing']:
                fail('VERIFICATION_FAILED', 'retained voice listing differs from the verified observation', 'voices')
            for stage, (command, names, limit) in stage_commands(prepared['rateWpm'], recorded['espeakng'], selected(prepared)).items():
                submission = read_json(directory, stage + '-submission.json')
                interpreter = submission.get('interpreter', {}).get('executable') if isinstance(submission.get('interpreter'), dict) else None
                native = submission.get('nativeCommand')
                if (not isinstance(interpreter, str) or not os.path.isabs(interpreter) or not isinstance(native, list) or len(native) != 2
                        or native[0] != interpreter or Path(native[1]).name != stage + '-launcher.py'
                        or type(submission.get('exitCode')) is not int or submission['exitCode'] != 0):
                    fail('VERIFICATION_FAILED', 'native command or completion record differs', stage)
                if bounded(directory / (stage + '-launcher.py'), limit=MAX_LOG_BYTES).decode() != launcher(stage, names, command, limit):
                    fail('VERIFICATION_FAILED', 'trusted native launcher differs', stage)
                if not same_json(read_json(directory, stage + '-inputs.json'), {n: digest(directory, n, held=held) for n in names}):
                    fail('VERIFICATION_FAILED', 'native input binding differs', stage)
                if stage == 'narrate' and (bounded(directory / (stage + '.stdout'), limit=MAX_LOG_BYTES) or bounded(directory / (stage + '.stderr'), limit=MAX_LOG_BYTES)):
                    fail('VERIFICATION_FAILED', 'a silent native stage logged output', stage)
                if stage != 'narrate' and bounded(directory / (stage + '.stderr'), limit=MAX_LOG_BYTES):
                    fail('VERIFICATION_FAILED', 'a native stage logged an error', stage)
            remaining_timeout(VERIFY_TIMEOUT)
            verified = {'verified': True, 'operation': 'narrate', 'artifacts': 2,
                        'audio': {'sampleRate': SAMPLE_RATE, 'channels': CHANNELS, 'frames': observation['frames']},
                        'bytes': {'text': len(held['captured.txt']), 'wav': len(observation['published'])},
                        'pcmSha256': sha(observation['pcm']),
                        'runtime': {'espeakng': observation['identity'], 'dataFingerprint': observation['dataFingerprint']},
                        **({'voice': prepared['voice']} if 'voice' in prepared else {})}
            if require_result and not same_json(result_claims(recorded_result), result_claims(verified)):
                fail('VERIFICATION_FAILED', 'retained result claims differ from the verified observation')
            return verified
    except (OSError, ValueError, KeyError, TypeError, IndexError, AttributeError, UnicodeError, RecursionError, StopIteration, struct.error) as error:
        fail('VERIFICATION_FAILED', 'invalid retained narration evidence: %s %s' % (type(error).__name__, str(error)[:80]))


def reusableInputs(document):
    prepared = plan(document)
    if 'text' in prepared:
        return {}    # the literal script is part of the document; there is no external input
    source = prepared['source']
    data = read_source(source, '$.source')
    text_facts(data, '$.source')
    return {source: sha(data)}


def verify(directory, require_result=True, *, executable=None):
    return verify_semantic(directory, runtime(executable), require_result)


from schemaxis.adaptor_runtime import bind as _bind_runtime
_bind_runtime(globals())
