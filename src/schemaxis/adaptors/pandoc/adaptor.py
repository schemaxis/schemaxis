# Copyright (C) 2026 David L F Gaden
"""Closed report model, trusted Pandoc AST and independent document inspection."""
import base64
from decimal import Decimal
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import stat
import struct
import sys
import time
import zlib

from schemaxis.artifacts import atomic_json
from schemaxis.core.declarations import validate_arguments
from schemaxis.core import timed_text
from schemaxis.core.faults import Fault, SchemaxisError
from schemaxis.dispatch import cancellation_requested
from schemaxis.errors import fail, keys
from schemaxis.native_command import execute

VERSION = 'schemaxis.pandoc/1'
MAX_BYTES = 16 * 1024 * 1024
TEXT = {'type': 'string', 'minLength': 1, 'maxLength': 2048, 'required': True}
CELL = {**TEXT, 'maxLength': 256}
PARAGRAPH = {'type': 'object', 'properties': {
    'kind': {'type': 'enum', 'values': ['paragraph'], 'required': True}, 'text': TEXT}}
TABLE = {'type': 'object', 'properties': {
    'kind': {'type': 'enum', 'values': ['table'], 'required': True},
    'columns': {'type': 'array', 'items': CELL, 'minItems': 1, 'maxItems': 8, 'required': True},
    'rows': {'type': 'array', 'items': {'type': 'array', 'items': CELL, 'minItems': 1, 'maxItems': 8},
             'minItems': 1, 'maxItems': 64, 'required': True}}}
# A transcript block names one retained machine-draft segments.json; planning checks its shape only, and the run captures,
# validates and binds the bytes. `path` is a plain string position, so a workflow handoff can supply it.
SHA = {'type': 'string', 'minLength': 64, 'maxLength': 64}
TIME_FORMATS = ['milliseconds', 'timecode']
TRANSCRIPT = {'type': 'object', 'properties': {
    'kind': {'type': 'enum', 'values': ['transcript'], 'required': True},
    'segments': {'type': 'object', 'required': True, 'properties': {'path': {**TEXT, 'maxLength': 4096}, 'sha256': SHA}},
    'timeFormat': {'type': 'enum', 'values': TIME_FORMATS}}}
MAX_TRANSCRIPTS = 2
TRANSCRIPT_COLUMNS = ['Start (ms)', 'End (ms)', 'Text']
# An explicit `timeFormat` of `timecode` shows the same integral-millisecond cue times as HH:MM:SS.mmm; an absent or `milliseconds`
# field publishes the columns above exactly as earlier reports did.
TIMECODE_COLUMNS = ['Start (HH:MM:SS.mmm)', 'End (HH:MM:SS.mmm)', 'Text']
# Pandoc 3.12.1 clamps DOCX pictures to its page text width (5334000 EMU = 148.17 mm) and writes HTML widths to five
# decimals, so only these widths reach both publications as authored. Reports verified before this limit carry the
# earlier 150 mm ceiling; the retained schema below re-plans them without changing how their evidence is inspected.
WIDTH_MAXIMUM = 148
RETAINED_WIDTH_MAXIMUM = 150
WIDTH_DECIMALS = 5
# An optional report-level `epub` object adds one EPUB 3 publication. Its single author declaration is the book language,
# a plain ASCII tag such as en, fr-CA or zh-Hans-CN; the route never detects a language or certifies that the text is in it.
EPUB = {'type': 'object', 'properties': {'language': {'type': 'string', 'minLength': 2, 'maxLength': 35, 'required': True}}}
# An optional report-level `metadata` object declares the creators and a one-paragraph summary carried by every selected publication.
# Plain Unicode text only (the report's own text rule), no other metadata keys, markup, links or identity claims. Authors keep their
# declared order, are never split or joined by this route and may not contain a semicolon, because Word stores the creator list as one
# '; ' joined string and a semicolon inside a name could not be told apart from a separator.
MAX_AUTHORS = 8
MAX_AUTHOR = 100
MAX_DESCRIPTION = 1000
METADATA = {'type': 'object', 'properties': {
    'authors': {'type': 'array', 'items': {'type': 'string', 'minLength': 1, 'maxLength': MAX_AUTHOR}, 'minItems': 1, 'maxItems': MAX_AUTHORS},
    'description': {'type': 'string', 'minLength': 1, 'maxLength': MAX_DESCRIPTION}}}


def options(width_maximum):
    image = {'type': 'object', 'properties': {
        'kind': {'type': 'enum', 'values': ['image'], 'required': True},
        'source': {**TEXT, 'maxLength': 4096}, 'alt': {**TEXT, 'maxLength': 256},
        'widthMm': {'type': 'number', 'minimum': 10, 'maximum': width_maximum, 'default': 80}}}
    section = {'type': 'object', 'properties': {
        'heading': {**TEXT, 'maxLength': 160},
        'level': {'type': 'integer', 'minimum': 1, 'maximum': 3, 'default': 1},
        'content': {'type': 'array', 'items': {'type': 'union', 'options': [PARAGRAPH, TABLE, image, TRANSCRIPT]},
                    'minItems': 1, 'maxItems': 32, 'required': True}}}
    return {'title': {**TEXT, 'maxLength': 160},
            'sections': {'type': 'array', 'items': section, 'minItems': 1, 'maxItems': 32, 'required': True}, 'epub': EPUB, 'metadata': METADATA}


OPTIONS = options(WIDTH_MAXIMUM)
RETAINED_OPTIONS = options(RETAINED_WIDTH_MAXIMUM)
DECLARATIONS = {'report': {'native': 'Pandoc JSON AST: Header / Para / Table / Image; html5 / docx writers; docx reader',
    'kinds': ['text', 'file'], 'inputs': {}, 'options': {k: {'value': v} for k, v in OPTIONS.items()}}}
LOSSES = ['Plain text only: no authored markup, scripts, links, formulas, citations, lists, styles or filters.',
    'Tables contain one header row and rectangular text cells; no merged cells, numeric types or formula semantics.',
    'Default Pandoc typography and pagination are not an exact page-layout contract; no PDF publication or visual equivalence claim.',
    'PNG bytes and alt text are retained; image display width is millimetres, aspect ratio is retained, and colour management/accessibility conformance are not certified.',
    'Section order and heading levels are preserved; generated identifiers and writer metadata are not authored interchange contracts.']
# Plans written before reviewed documents were accepted carry this text; verification re-plans them unchanged.
LEGACY_TRANSCRIPT_LOSS = ('A transcript block publishes the retained machine-draft segments.json cues as one provenance paragraph and one three-column table: '
    'cue text and integral-millisecond times are exact, but the status is always machine-draft (a person has not reviewed it and accuracy is not certified), '
    'speakers, word times, confidence and caption cue formats are not published, and the document is refused, never truncated, beyond '
    f'{timed_text.MAX_CUES} cues, {timed_text.MAX_CUE_CHARACTERS} characters per cue or {MAX_TRANSCRIPTS} transcript blocks per report.')
TRANSCRIPT_LOSS = ('A transcript block publishes one retained timed-text document as one provenance paragraph and one three-column table: cue text and '
    'integral-millisecond times are exact. A whisper.cpp machine-draft segments.json is shown as machine-draft (a person has not reviewed it and accuracy is not certified); '
    'a schemaxis.timedtext.reviewed/1 document from the host-only whisper.cpp corrections route is shown with its author-declared status (human-corrected or '
    'human-reviewed-unchanged), note, correction count and basis digest, and the status is a declaration: reviewer identity, hearing the audio, accuracy and accessibility are never verified or certified. '
    'Speakers, word times, confidence and caption cue formats are not published, and the document is refused, never truncated, beyond '
    f'{timed_text.MAX_CUES} cues, {timed_text.MAX_CUE_CHARACTERS} characters per cue or {MAX_TRANSCRIPTS} transcript blocks per report.')
TIMECODE_LOSS = ('A transcript block with timeFormat timecode shows each cue start and end as elapsed HH:MM:SS.mmm (hours, minutes, seconds and milliseconds from the '
    'start of the recording, hours not limited to two digits), computed exactly from the recorded integer milliseconds without rounding; it is a reading format for the '
    'same cue times, not a wall-clock time, a caption file, or a claim of recognition accuracy, timing accuracy, readability or accessibility.')

EPUB_LOSS = ('An epub declaration adds one EPUB 3 publication (report.epub, artifact index 3) written by the official Pandoc EPUB 3 writer from the same trusted report model as the HTML and DOCX publications: '
    'one chapter file per level 1 section, the title, headings, paragraphs, tables and embedded PNG images in authored order, with Pandoc\'s default stylesheet, navigation and fixed 1970-01-01 dates. '
    'The package and its content are checked by independent host code and by a fresh Pandoc EPUB readback, a bounded structural proof only: '
    'it is not an EPUBCheck conformance, reading-system or device rendering, accessibility, language-detection or language-accuracy claim, and the language is the author\'s declaration. '
    'No cover, fonts, scripts, links, custom styles, metadata fields or Calibre conversion are supported, and the package is refused, never truncated, beyond its byte and member limits.')

METADATA_LOSS = ('A metadata declaration publishes the author-declared creators and description as plain text in each selected publication: standalone HTML '
    '(author and description meta elements, and one visible author line each in the title block), DOCX (the core-properties creator joined with "; " and description, and one Author-style '
    'title-block paragraph each) and, with epub, EPUB 3 (one dc:creator each, which Pandoc marks with the marc:relators role aut, one dc:description, and one author line each on the title page). '
    'The description is metadata and is not shown in the text of any publication. Authors and description are declarations by whoever wrote the report: nothing verifies who the authors are, '
    'that they wrote or approved the report, or that the description is accurate, and the description does not imply accessibility, review or peer review. '
    f'At most {MAX_AUTHORS} distinct authors of at most {MAX_AUTHOR} characters without a semicolon and one description of at most {MAX_DESCRIPTION} characters are accepted; no other metadata fields, markup, links, '
    'identifiers, dates, rights or subjects are supported, and the characters count toward the report text budget.')


# Formatting characters that this route does not support in a published transcript or report: bidirectional
# embeddings/overrides/isolates, word joiner and invisible operators, byte order mark, the Mongolian vowel
# separator, interlinear annotation and noncharacters. Characters that ordinary multilingual text depends on stay
# accepted: ZWNJ/ZWJ (U+200C/200D), LRM/RLM (U+200E/200F) and the Arabic letter mark (U+061C), and, in the narrow
# forms below, zero-width space between Thai/Lao/Myanmar/Khmer letters and well-formed emoji subdivision flags.
# This is an explicit list of unsupported formatting, not a Unicode-safety, confusable or anti-spoofing policy:
# other invisible or lookalike characters (soft hyphen, Hangul fillers, homoglyphs) are not detected.
HOSTILE = re.compile('[\u180e\u202a-\u202e\u2060-\u2064\u2066-\u2069\ufdd0-\ufdef\ufeff\ufff9-\ufffb\U0000fffe\U0000ffff]'
                     '|[\U0001fffe\U0001ffff\U0002fffe\U0002ffff\U0003fffe\U0003ffff'
                     '\U0004fffe\U0004ffff\U0005fffe\U0005ffff\U0006fffe\U0006ffff\U0007fffe\U0007ffff\U0008fffe\U0008ffff'
                     '\U0009fffe\U0009ffff\U000afffe\U000affff\U000bfffe\U000bffff\U000cfffe\U000cffff\U000dfffe\U000dffff'
                     '\U000efffe\U000effff\U000ffffe\U000fffff\U0010fffe\U0010ffff]')
# U+1F3F4 + subdivision tag letters/digits + U+E007F, e.g. England, Scotland and Wales. Other tag characters are refused.
FLAG_SEQUENCE = re.compile('\U0001f3f4[\U000e0030-\U000e0039\U000e0061-\U000e007a]{3,6}\U000e007f')
TAGS = re.compile('[\U000e0000-\U000e007f]')
# Thai, Lao, Myanmar and Khmer scripts write words without spaces, so ZWSP marks a break between their letters.
ZWSP_SCRIPTS = re.compile('[\u0e00-\u0e7f\u0e80-\u0eff\u1000-\u109f\u1780-\u17ff\u19e0-\u19ff\uaa60-\uaa7f]')


def hidden_format(value):
    """Return the first unsupported formatting character, or None; the allowed forms are documented above."""
    found = HOSTILE.search(value)
    if found: return found.group()
    found = TAGS.search(FLAG_SEQUENCE.sub('', value))
    if found: return found.group()
    for match in re.finditer('\u200b', value):
        i = match.start()
        if not (0 < i < len(value) - 1 and ZWSP_SCRIPTS.match(value[i-1]) and ZWSP_SCRIPTS.match(value[i+1])): return '\u200b'
    return None


def plain(value, location):
    if hidden_format(value) is not None:
        fail('INVALID_REPORT_TEXT', 'remove unsupported formatting characters: bidirectional embeddings/overrides/isolates, word joiner, byte order mark, '
             'noncharacters, stray tag characters, and zero-width space outside Thai, Lao, Myanmar or Khmer text', location)
    if value != value.strip() or any(ord(c) < 32 or 127 <= ord(c) <= 159 or c in '\ufffe\uffff' or 0xD800 <= ord(c) <= 0xDFFF or c in '\u2028\u2029' for c in value) or '  ' in value or any(c.isspace() and c != ' ' for c in value):
        fail('INVALID_REPORT_TEXT', 'use nonempty plain text with single spaces, no control characters or line breaks', location)
    return value


def check_time_formats(document):
    """Refuse a transcript `timeFormat` that is not one of the two names, at the field itself and before any file or native work."""
    sections = document.get('sections')
    for i, section in enumerate(sections if isinstance(sections, list) else []):
        content = section.get('content') if isinstance(section, dict) else None
        for j, block in enumerate(content if isinstance(content, list) else []):
            if isinstance(block, dict) and block.get('kind') == 'transcript' and 'timeFormat' in block:
                value = block['timeFormat']
                if type(value) is not str or value not in TIME_FORMATS:
                    fail('INVALID_ARGUMENT', 'select timeFormat milliseconds or timecode (booleans, numbers and other names are refused), or omit it for milliseconds',
                         f'$.sections[{i}].content[{j}].timeFormat', observed=repr(value)[:80])


def check_epub(document):
    """Refuse a malformed `epub` declaration at the field itself, before any file or native work."""
    if 'epub' not in document: return
    from .epub import valid_language
    value = document['epub']
    if type(value) is not dict: fail('INVALID_ARGUMENT', 'epub is an object with one required field, language; omit epub for no EPUB publication', '$.epub', observed=repr(value)[:80])
    unknown = sorted(str(k) for k in value if k != 'language')
    if unknown: fail('UNKNOWN_ARGUMENT', 'epub accepts only language; covers, metadata, styles, fonts and paths are not supported: ' + ', '.join(unknown)[:80], '$.epub')
    if 'language' not in value: fail('MISSING_ARGUMENT', 'epub requires language, for example en or fr-CA', '$.epub.language')
    if not valid_language(value['language']):
        fail('INVALID_ARGUMENT', 'select a plain ASCII language tag of 2-3 letters with up to three hyphen subtags (for example en, fr-CA, zh-Hans-CN), at most 35 characters; booleans, numbers and other text are refused',
             '$.epub.language', observed=repr(value['language'])[:80])


def check_metadata(document):
    """Refuse a malformed `metadata` declaration at the offending field, before any file or native work."""
    if 'metadata' not in document: return
    value = document['metadata']
    if type(value) is not dict: fail('INVALID_ARGUMENT', 'metadata is an object with authors, description or both; omit metadata to publish none', '$.metadata', observed=repr(value)[:80])
    unknown = sorted(str(k) for k in value if k not in ('authors', 'description'))
    if unknown: fail('UNKNOWN_ARGUMENT', 'metadata accepts only authors and description; other keys, markup and links are not supported: ' + ', '.join(unknown)[:80], '$.metadata')
    if not value: fail('MISSING_ARGUMENT', 'metadata must declare authors, description or both; omit metadata to publish none', '$.metadata')
    if 'authors' in value:
        authors = value['authors']
        if type(authors) is not list or not 1 <= len(authors) <= MAX_AUTHORS:
            fail('INVALID_ARGUMENT', f'authors is a list of 1-{MAX_AUTHORS} plain text names, in the order to publish them', '$.metadata.authors', observed=repr(authors)[:80])
        for i, author in enumerate(authors):
            if type(author) is not str or not 1 <= len(author) <= MAX_AUTHOR:
                fail('INVALID_ARGUMENT', f'each author is a plain text string of 1-{MAX_AUTHOR} characters (booleans, numbers, objects and empty text are refused)', f'$.metadata.authors[{i}]', observed=repr(author)[:80])
    if 'description' in value:
        description = value['description']
        if type(description) is not str or not 1 <= len(description) <= MAX_DESCRIPTION:
            fail('INVALID_ARGUMENT', f'description is plain text of 1-{MAX_DESCRIPTION} characters (booleans, numbers, objects and empty text are refused)', '$.metadata.description', observed=repr(description)[:80])


def metadata_text(metadata, characters=0):
    """Apply the report's plain-text rule to the declared authors and description; returns the characters they add to the report budget."""
    authors = metadata.get('authors', [])
    for i, author in enumerate(authors):
        plain(author, f'$.metadata.authors[{i}]'); characters += len(author)
        if ';' in author:
            fail('INVALID_ARGUMENT', 'remove the semicolon from this author: Word stores creators as one list joined with semicolons, so a semicolon inside a name could not be told from a separator', f'$.metadata.authors[{i}]', observed=repr(author)[:80])
        if author in authors[:i]:
            fail('INVALID_ARGUMENT', 'list each author once (names are compared exactly, case and spacing included); add a distinguishing detail to tell two people with the same name apart', f'$.metadata.authors[{i}]', observed=repr(author)[:80])
    if 'description' in metadata: plain(metadata['description'], '$.metadata.description'); characters += len(metadata['description'])
    return characters


def metadata_capture(metadata):
    """The retained record of the declared metadata: the exact text, its character count and the SHA-256 of its canonical JSON form."""
    canonical = json.dumps(metadata, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode('utf-8')
    return {**metadata, 'characters': metadata_text(metadata), 'sha256': hashlib.sha256(canonical).hexdigest()}


def plan(document, *, retained=False):
    """Plan a report; `retained` re-plans a stored authored.json under the limits it was accepted with."""
    keys(document, ('version', 'operation', *OPTIONS), '$')
    if document.get('version') != VERSION: fail('UNSUPPORTED_VERSION', 'expected ' + VERSION)
    if document.get('operation') != 'report': fail('UNKNOWN_FILTER', 'select report')
    check_time_formats(document); check_epub(document); check_metadata(document)
    prepared = validate_arguments(RETAINED_OPTIONS if retained else OPTIONS, {k: v for k, v in document.items() if k in OPTIONS})
    plain(prepared['title'], '$.title')
    previous = 0; count = 0; characters = metadata_text(prepared['metadata'], len(prepared['title'])) if 'metadata' in prepared else len(prepared['title']); images = 0; transcripts = 0; timecodes = 0
    for i, section in enumerate(prepared['sections']):
        at = f'$.sections[{i}]'; level = section['level']
        if level > previous + 1: fail('INVALID_HEADING_ORDER', 'begin with level 1 and increase by at most one; descending levels may skip', at + '.level')
        previous = level; plain(section['heading'], at + '.heading'); characters += len(section['heading'])
        for j, block in enumerate(section['content']):
            where = at + f'.content[{j}]'; count += 1
            if block['kind'] == 'paragraph': plain(block['text'], where + '.text'); characters += len(block['text'])
            elif block['kind'] == 'table':
                if any(len(row) != len(block['columns']) for row in block['rows']):
                    fail('INVALID_REPORT_TABLE', 'each row must have exactly one text cell per declared column', where + '.rows')
                for r, row in enumerate([block['columns'], *block['rows']]):
                    for c, value in enumerate(row): plain(value, where + f'.cells[{r}][{c}]'); characters += len(value)
            elif block['kind'] == 'transcript':
                transcripts += 1; timecodes += block.get('timeFormat') == 'timecode'; reference = block['segments']; at_path = where + '.segments.path'; path = reference['path']
                if '\0' in path or not path.startswith('/') or '..' in Path(path).parts or Path(path).suffix.lower() != '.json':
                    fail('INVALID_TRANSCRIPT_SOURCE', 'select an absolute local segments.json path without parent references (the whisper.cpp route publishes it)', at_path)
                if 'sha256' in reference and not timed_text.HEX.fullmatch(reference['sha256']):
                    fail('INVALID_SHA256', 'use 64 lowercase hexadecimal digits', where + '.segments.sha256')
            else:
                plain(block['alt'], where + '.alt'); images += 1
                if not retained and -Decimal(repr(block['widthMm'])).as_tuple().exponent > WIDTH_DECIMALS:
                    fail('INVALID_REPORT_IMAGE', f'give widthMm with at most {WIDTH_DECIMALS} decimal places; Pandoc rounds the HTML width to '
                         'that precision, so a longer value cannot be verified in both publications', where + '.widthMm')
                source = Path(block['source'])
                if not source.is_absolute() or source.suffix.lower() != '.png':
                    fail('INVALID_REPORT_IMAGE', 'select an absolute local PNG path; remote URLs and other formats are unsupported', where + '.source')
    if count > 128 or characters > 65536 or images > 8:
        fail('REPORT_RESOURCE_LIMIT', 'report permits at most 128 content blocks, 65536 text characters and 8 images', '$.sections')
    if transcripts > MAX_TRANSCRIPTS:
        fail('REPORT_RESOURCE_LIMIT', f'report permits at most {MAX_TRANSCRIPTS} transcript blocks; publish further transcripts in another report', '$.sections')
    losses = [*LOSSES, TRANSCRIPT_LOSS] if transcripts else LOSSES
    if timecodes: losses = [*losses, TIMECODE_LOSS]
    if 'epub' in prepared: losses = [*losses, EPUB_LOSS]
    if 'metadata' in prepared: losses = [*losses, METADATA_LOSS]
    return {'version': 'schemaxis.pandoc.plan/1', 'operation': 'report', **prepared, 'losses': losses}


def schema():
    from schemaxis.schema import DRAFT, argument_schema, object_schema
    return {'$schema': DRAFT, **object_schema({'version': {'const': VERSION}, 'operation': {'const': 'report'},
        **{k: argument_schema(v) for k, v in OPTIONS.items()}}, ['version', 'operation', 'title', 'sections'])}


def query(document):
    plan(document); return ['report'], {}


def resources(document, execution, identity):
    if execution.get('threads', 1) != 1: fail('INVALID_EXECUTION', 'report rendering uses one process thread', identity)
    return {'threads': 1}


def bounded(path, code='VERIFICATION_FAILED', limit=MAX_BYTES):
    path = Path(path)
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NONBLOCK', 0) | getattr(os, 'O_NOFOLLOW', 0))
        with os.fdopen(fd, 'rb') as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size > limit: raise ValueError('not a bounded regular file')
            data = stream.read(limit + 1)
        if len(data) > limit: raise ValueError('byte budget exceeded')
        return data
    except (OSError, ValueError) as error:
        fail(code, 'select intact bounded regular evidence: ' + str(error), str(path))


def png(data, location):
    """Validate closed 8-bit non-interlaced RGB/RGBA PNG and bounded scanline data."""
    try:
        if data[:8] != b'\x89PNG\r\n\x1a\n': raise ValueError('PNG signature')
        position = 8; chunks = []; compressed = bytearray(); width = height = colour = None
        while position < len(data):
            length = struct.unpack('>I', data[position:position+4])[0]; kind = data[position+4:position+8]
            body = data[position+8:position+8+length]; crc = data[position+8+length:position+12+length]
            if length > 4*1024*1024 or len(body) != length or len(crc) != 4 or struct.unpack('>I', crc)[0] != zlib.crc32(kind+body): raise ValueError('chunk CRC/length')
            chunks.append(kind); position += length+12
            if kind == b'IHDR':
                width,height,depth,colour,compression,filtering,interlace = struct.unpack('>IIBBBBB', body)
                if not 1 <= width <= 2048 or not 1 <= height <= 2048 or width*height > 1048576 or depth != 8 or colour not in (2,6) or (compression,filtering,interlace) != (0,0,0): raise ValueError('unsupported dimensions/colour/interlace')
            elif kind == b'IDAT': compressed.extend(body)
            elif kind != b'IEND': raise ValueError('only IHDR/IDAT/IEND chunks are supported; export a plain RGB/RGBA PNG')
        if chunks[1:-1] != [b'IDAT'] * (len(chunks)-2) or chunks[0] != b'IHDR' or chunks[-1] != b'IEND' or chunks.count(b'IHDR') != 1 or chunks.count(b'IEND') != 1 or b'IDAT' not in chunks or body or position != len(data): raise ValueError('chunk order')
        expected = (width*(3 if colour == 2 else 4)+1)*height
        inflater = zlib.decompressobj(); decoded = inflater.decompress(bytes(compressed), expected+1)
        if len(decoded) != expected or not inflater.eof or inflater.unused_data or inflater.unconsumed_tail: raise ValueError('scanline size')
        stride = width*(3 if colour == 2 else 4)+1
        if any(decoded[y*stride] > 4 for y in range(height)): raise ValueError('PNG filter')
        return {'width': width, 'height': height, 'sha256': hashlib.sha256(data).hexdigest()}
    except (ValueError, IndexError, struct.error, zlib.error, TypeError) as error:
        fail('INVALID_REPORT_IMAGE', 'use a plain bounded 8-bit RGB/RGBA PNG: ' + str(error), location)


def image_blocks(prepared):
    for i, section in enumerate(prepared['sections']):
        for j, block in enumerate(section['content']):
            if block['kind'] == 'image': yield i, j, block


def transcript_blocks(prepared):
    for i, section in enumerate(prepared['sections']):
        for j, block in enumerate(section['content']):
            if block['kind'] == 'transcript': yield i, j, block


def refuse(code, message, location, recovery, **observed):
    raise SchemaxisError(Fault(code, message, location, 'pipeline', observed=observed, recovery=recovery))


def read_source(path, location):
    """Read one retained segments.json through a single descriptor: no symlink, bounded, regular file."""
    limit = timed_text.MAX_DOCUMENT_BYTES
    recovery = 'select the regular segments.json published by the whisper.cpp route (or a workflow handoff of it), not a link, directory or other file'
    try: fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NONBLOCK', 0) | getattr(os, 'O_NOFOLLOW', 0))
    except (FileNotFoundError, NotADirectoryError):
        refuse('TRANSCRIPT_SOURCE_MISSING', 'the transcript source file does not exist', location, 'run or restore the transcription so its segments.json exists, then plan again', path=path)
    except OSError as error:
        refuse('TRANSCRIPT_SOURCE_INVALID', 'the transcript source cannot be opened: ' + error.strerror.lower() if error.strerror else 'the transcript source cannot be opened', location, recovery, path=path)
    try:
        info = os.fstat(fd)
        if stat.S_ISREG(info.st_mode) and info.st_size <= limit:
            with os.fdopen(fd, 'rb') as stream: data = stream.read(limit + 1)
        else: data = None; os.close(fd)
    except OSError as error:
        refuse('TRANSCRIPT_SOURCE_INVALID', 'the transcript source cannot be read: ' + str(error.strerror or error).lower(), location, recovery, path=path)
    if data is None: refuse('TRANSCRIPT_SOURCE_INVALID', f'the transcript source must be a regular file of at most {limit} bytes', location, recovery, path=path)
    if len(data) > limit: refuse('TRANSCRIPT_SOURCE_INVALID', f'the transcript source exceeds {limit} bytes', location, recovery, path=path)
    return data


def checked_cues(view, location):
    """The route's own text rule over every cue; a cue Pandoc could not publish exactly is refused, never repaired."""
    for k, cue in enumerate(view['cues']): plain(cue['text'], f'{location}.segments[{k}].text')


def transcript_view(data, location, pin=None):
    view = timed_text.parse(data, expected_sha256=pin, location=location)
    checked_cues(view, location)
    if view.get('review'): plain(view['review']['note'], location + '.review.note')
    return view


def timecode(milliseconds):
    """Elapsed HH:MM:SS.mmm from integer milliseconds by integer arithmetic only; hours are never capped or wrapped."""
    if type(milliseconds) is not int or milliseconds < 0: raise ValueError('a timecode needs a non-negative integer number of milliseconds')
    return '%02d:%02d:%02d.%03d' % (milliseconds // 3600000, milliseconds // 60000 % 60, milliseconds // 1000 % 60, milliseconds % 1000)


def transcript_summary(block, view):
    summary = {'source': block['segments']['path'], 'kind': 'timed-text', 'status': view['status'], 'sha256': view['sha256'], 'bytes': view['bytes'],
               'cues': len(view['cues']), 'characters': sum(len(c['text']) for c in view['cues'])}
    # Only a reviewed/2 document records deletions; the summary of every earlier document keeps exactly its earlier members.
    if view['source'] == timed_text.REVIEWED2_VERSION: summary.update(sourceCues=view['review']['sourceCueCount'], deletedCues=view['review']['deletionCount'])
    # A reviewed/3 document additionally records author-edited cue times, by original source index.
    if view['source'] == timed_text.REVIEWED3_VERSION:
        review = view['review']
        summary.update(sourceCues=review['sourceCueCount'], deletedCues=review['deletionCount'], timingEditedCues=review['timingEditCount'],
                       timingEditedSourceIndices=list(review['timingEditedIndices']))
    if 'timeFormat' in block: summary['timeFormat'] = block['timeFormat']
    return summary

def legacy_cue_grammar(block, view):
    """True for the one transcript an earlier report wrote with the grammar "1 cues": a one-cue machine draft without timeFormat or segmentation."""
    return (view['source'] == timed_text.SOURCE_VERSION and len(view['cues']) == 1 and 'timeFormat' not in block and not view['segmentation'])


def transcript_content(view, time_format=None, legacy_plural=False):
    """Provenance paragraph, header cells and rows for a validated machine-draft or author-declared reviewed transcript.

    `time_format` is the block's optional `timeFormat`: absent or `milliseconds` publishes integer milliseconds, `timecode` HH:MM:SS.mmm.
    `legacy_plural` writes the earlier "1 cues" grammar; only `verify` sets it, for a retained report written that way."""
    count = len(view['cues']); cues = f'{count} cues' if legacy_plural else f'{count} cue{"" if count == 1 else "s"}'
    clock = time_format == 'timecode'
    duration = timecode(view['durationMs']) if clock else f'{view["durationMs"]} ms'
    unit = ('times are elapsed time from the start of the recording written as HH:MM:SS.mmm (hours, minutes, seconds, milliseconds)' if clock
            else 'times are elapsed milliseconds from the start of the recording')
    ending = (f'Language {view["language"]}; {cues}; audio duration {duration}; {unit}. '
              f'SHA-256 of the segments file {view["sha256"]}, audio {view["audioSha256"]} and model {view["modelSha256"]}.')
    review = view.get('review')
    if review is None:
        paragraph = (f'Status: {view["status"]}. This transcript is automatic speech recognition output from {view["source"]}; a person has not reviewed it '
                     f'and its accuracy is not certified. {ending}')
    elif view['source'] in (timed_text.REVIEWED2_VERSION, timed_text.REVIEWED3_VERSION):
        source, deleted = review['sourceCueCount'], review['deletionCount']
        plural = lambda n: f'{n} cue{"" if n == 1 else "s"}'
        parts = [f'{plural(review["correctionCount"])} replaced by authored text (source cue indexes {", ".join(map(str, review["correctedIndices"]))})'] if review['correctionCount'] else []
        if deleted: parts.append(f'{plural(deleted)} of {source} deleted by the author (source cue indexes {", ".join(map(str, review["deletedSourceIndices"]))})')
        retimed = view['source'] == timed_text.REVIEWED3_VERSION and review['timingEditCount']
        if retimed: parts.append(f'{plural(review["timingEditCount"])} given author-edited start and end times (source cue indexes {", ".join(map(str, review["timingEditedIndices"]))})')
        edits = '; '.join(parts) if parts else ('no cue text or time changed' if view['source'] == timed_text.REVIEWED3_VERSION else 'no cue text changed')
        retained = (f'; the remaining {plural(count)} are numbered from zero as published' if count and deleted else
                    f'; the author deleted every cue, so no cues are retained and no spoken words are published here, and this is the author\'s declaration, not evidence that the recording holds no speech' if not count else '')
        paragraph = (f'Status: {view["status"]}, declared by the author of the corrections. This transcript began as automatic speech recognition output '
                     f'(machine draft SHA-256 {review["basisSha256"]}, {plural(source)}); {edits}{retained}. Review note (author\'s words): "{review["note"]}". The status is a declaration: who reviewed it, '
                     f'whether the audio was heard and whether the words are accurate are not verified or certified. {ending}')
        if view['source'] == timed_text.REVIEWED3_VERSION:
            n = review['timingEditCount']
            if not count:
                times = 'No cue times are shown because no cues are retained.'
            elif n:
                others = f' The other {plural(count - n)} {"shows" if count - n == 1 else "show"} the original machine times as recorded in this document.' if count > n else ''
                times = (f'The times shown for the {plural(n)} listed above are edited times recorded in this document as the author\'s, not the machine draft\'s; '
                         f'the original machine times are not shown here.{others}')
            else:
                times = ('The author edited no cue times; the times shown are the machine draft\'s original times as recorded in this document, '
                         'and Pandoc did not check them against the draft file.')
            paragraph += f' {times}' + (' Whether any time is synchronized with the audio is not verified or certified.' if count else '')
    else:
        edits = (f'{review["correctionCount"]} cue{"" if review["correctionCount"] == 1 else "s"} replaced by authored text (cue indexes {", ".join(map(str, review["correctedIndices"]))})'
                 if review['correctionCount'] else 'no cue text changed')
        paragraph = (f'Status: {view["status"]}, declared by the author of the corrections. This transcript began as automatic speech recognition output '
                     f'(machine draft SHA-256 {review["basisSha256"]}); {edits}. Review note (author\'s words): "{review["note"]}". The status is a declaration: who reviewed it, '
                     f'whether the audio was heard and whether the words are accurate are not verified or certified. {ending}')
    target = view['segmentation']
    if target: paragraph += f' Cue length target {target["maxSegmentLength"]} characters, not enforced; {target["cuesOverTarget"]} cue{"" if target["cuesOverTarget"] == 1 else "s"} exceed{"s" if target["cuesOverTarget"] == 1 else ""} it.'
    plain(paragraph, '$.transcript.provenance')
    # Empty reviewed/2 transcripts publish provenance only, in either time format.
    if not count: return paragraph, [], []
    if clock: return paragraph, TIMECODE_COLUMNS, [[timecode(c['startMs']), timecode(c['endMs']), c['text']] for c in view['cues']]
    return paragraph, TRANSCRIPT_COLUMNS, timed_text.rows(view)


def authored_characters(prepared):
    """Characters counted by `plan` toward the report budget, so captured transcripts can be added at run."""
    total = metadata_text(prepared['metadata'], len(prepared['title'])) if 'metadata' in prepared else len(prepared['title'])
    for section in prepared['sections']:
        total += len(section['heading'])
        for block in section['content']:
            if block['kind'] == 'paragraph': total += len(block['text'])
            elif block['kind'] == 'table': total += sum(len(v) for row in [block['columns'], *block['rows']] for v in row)
    return total


def reusableInputs(document):
    prepared = plan(document)
    inputs = {f'image-{i}-{j}': hashlib.sha256(bounded(b['source'], 'INVALID_REPORT_IMAGE', 4*1024*1024)).hexdigest()
              for i,j,b in image_blocks(prepared)}
    inputs.update({f'transcript-{i}-{j}': hashlib.sha256(read_source(b['segments']['path'], f'$.sections[{i}].content[{j}].segments.path')).hexdigest()
                   for i,j,b in transcript_blocks(prepared)})
    return inputs


def inlines(text):
    result = []
    for index, word in enumerate(text.split(' ')):
        if index: result.append({'t': 'Space'})
        result.append({'t': 'Str', 'c': word})
    return result


def table_ast(columns, rows):
    attr = ['', [], []]
    def row(values):
        return [attr, [[attr, {'t': 'AlignDefault'}, 1, 1, [{'t': 'Plain', 'c': inlines(value)}]] for value in values]]
    return {'t': 'Table', 'c': [attr, [None, []], [[{'t': 'AlignDefault'}, {'t': 'ColWidthDefault'}] for _ in columns],
        [attr, [row(columns)]], [[attr, 0, [], [row(r) for r in rows]]], [attr, []]]}


def retained_transcript(directory, i, j):
    return transcript_view(bounded(directory/f'transcript-{i}-{j}.json', limit=timed_text.MAX_DOCUMENT_BYTES), f'$.sections[{i}].content[{j}].segments')


def ast(prepared, api, directory):
    blocks = []; attr = ['', [], []]
    for i, section in enumerate(prepared['sections']):
        blocks.append({'t': 'Header', 'c': [section['level'], [f'section-{i+1}', [], []], inlines(section['heading'])]})
        for j, block in enumerate(section['content']):
            if block['kind'] == 'paragraph': blocks.append({'t': 'Para', 'c': inlines(block['text'])})
            elif block['kind'] == 'transcript':
                paragraph, columns, rows = transcript_content(retained_transcript(directory, i, j), block.get('timeFormat'), (i, j) in prepared.get('_earlierCues', ()))
                blocks.append({'t': 'Para', 'c': inlines(paragraph)})
                if columns: blocks.append(table_ast(columns, rows))
            elif block['kind'] == 'image':
                blocks.append({'t': 'Para', 'c': [{'t': 'Image', 'c': [['', [], [['width', f'{block["widthMm"]}mm']]],
                    inlines(block['alt']), ['data:image/png;base64,'+base64.b64encode(bounded(directory/f'image-{i}-{j}.png')).decode('ascii'), '']]}]})
            else: blocks.append(table_ast(block['columns'], block['rows']))
    meta = {'title': {'t': 'MetaInlines', 'c': inlines(prepared['title'])}}
    declared = prepared.get('metadata', {})
    # Pandoc's `author` is a list of inline strings and `description` a plain string; no other metadata key is ever written.
    if 'authors' in declared: meta['author'] = {'t': 'MetaList', 'c': [{'t': 'MetaInlines', 'c': inlines(a)} for a in declared['authors']]}
    if 'description' in declared: meta['description'] = {'t': 'MetaString', 'c': declared['description']}
    return {'pandoc-api-version': api, 'meta': meta, 'blocks': blocks}


def strict_json(data):
    """Parse retained JSON without duplicate keys, non-finite constants or unbounded nesting."""
    def pairs(items):
        if len({key for key, _ in items}) != len(items): raise ValueError('duplicate JSON object key')
        return dict(items)
    def constant(name): raise ValueError('non-finite JSON constant ' + name)
    try: return json.loads(data, object_pairs_hook=pairs, parse_constant=constant)
    except RecursionError: raise ValueError('JSON nesting exceeds the supported depth') from None


def read(directory, name):
    try: return strict_json(bounded(directory/name))
    except ValueError as error: fail('VERIFICATION_FAILED', 'malformed retained JSON: ' + str(error), str(directory/name))
def digest(directory, name): return hashlib.sha256(bounded(directory/name)).hexdigest()


def expected(prepared):
    blocks = []
    for i, section in enumerate(prepared['sections']):
        blocks.append({'kind': 'heading', 'level': section['level'], 'text': section['heading']})
        for j, block in enumerate(section['content']):
            if block['kind'] == 'paragraph': blocks.append({'kind': 'paragraph', 'text': block['text']})
            elif block['kind'] == 'table': blocks.append({'kind': 'table', 'rows': [block['columns'], *block['rows']]})
            elif block['kind'] == 'transcript':
                paragraph, columns, rows = transcript_content(retained_transcript(prepared['_directory'], i, j), block.get('timeFormat'), (i, j) in prepared.get('_earlierCues', ()))
                blocks.append({'kind': 'paragraph', 'text': paragraph})
                if columns: blocks.append({'kind': 'table', 'rows': [columns, *rows]})
            else: blocks.append({'kind': 'image', 'alt': block['alt'], 'sha256': digest(prepared['_directory'], f'image-{i}-{j}.png'),
                                'widthMm': block['widthMm']})
    return blocks


# job.json is the workflow coordinator's attempt record, added after the adaptor finishes.
COMMON = {'verification.json', 'result.json', 'publication-metadata.json', 'schema.snapshot.json', 'job.json'}
DIRECTORIES = {'.dispatch', 'native-data', 'reopened'}


def members(directory, expected, epub=False):
    """Reject undeclared files beside, or extra extracted media below, the verified publication."""
    allowed = set(expected) | COMMON
    sidecars = {name + '.metadata.json' for name in ('report.html', 'report.docx', 'report-summary.json', *(('report.epub',) if epub else ()))}
    for path in sorted(directory.iterdir()):
        name = path.name
        if name in DIRECTORIES:
            if path.is_symlink() or not path.is_dir(): fail('VERIFICATION_FAILED', 'retained directory differs', name)
        elif not (name in allowed or name in sidecars):
            fail('VERIFICATION_FAILED', 'undeclared file in report directory', name)
        elif path.is_symlink() or not path.is_file(): fail('VERIFICATION_FAILED', 'report directory member is not a regular file', name)
    reopened = directory/'reopened'
    if reopened.exists():
        found = set()
        for path in reopened.rglob('*'):
            if path.is_symlink(): fail('VERIFICATION_FAILED', 'native extracted media symlink unsupported', str(path.relative_to(directory)))
            if path.is_file(): found.add(path.relative_to(directory).as_posix())
            elif not path.is_dir(): fail('VERIFICATION_FAILED', 'native extracted media special file unsupported', str(path.relative_to(directory)))
        if found != {n for n in expected if n.startswith('reopened/')}: fail('VERIFICATION_FAILED', 'native extracted media membership differs', 'reopened')


def artifacts(directory, epub=False):
    """HTML 0, DOCX 1 and summary 2 as before; an EPUB publication is appended as index 3 and only when declared."""
    return [{'file': str(directory/name), 'kind': kind, 'sha256': digest(directory, name)}
            for name,kind in [('report.html','text'),('report.docx','file'),('report-summary.json','text'),*([('report.epub','file')] if epub else [])]]


def commands(executable, epub=None):
    native = {'version': [executable, '--version'],
        'api': [executable, '--from=markdown', '--to=json', '--output=api.json', 'empty.txt'],
        'html': [executable, '--from=json', '--to=html5', '--wrap=none', '--standalone', '--embed-resources', '--sandbox', '--output=report.html', 'report-input.json'],
        'docx': [executable, '--from=json', '--to=docx', '--standalone', '--sandbox', '--output=report.docx', 'report-input.json'],
        'reopen': [executable, '--from=docx', '--to=json', '--sandbox', '--extract-media=reopened', '--output=reopened.json', 'report.docx']}
    if epub:
        # The language is validated by `plan` to a plain ASCII tag that begins with a letter, so it cannot act as an option.
        native['epub'] = [executable, '--from=json', '--to=epub3', '--standalone', '--sandbox', '--metadata=lang:' + epub['language'], '--output=report.epub', 'report-input.json']
        native['epubreopen'] = [executable, '--from=epub', '--to=json', '--sandbox', '--output=epub-reopened.json', 'report.epub']
    return {stage: command+['--data-dir=native-data','+RTS','-M512M','-RTS'] for stage,command in native.items()}


def stage_inputs(stage, prepared):
    if stage == 'api': return ['empty.txt']
    if stage in ('html', 'docx', 'epub'): return ['report-input.json']
    if stage == 'reopen': return ['report.docx']
    if stage == 'epubreopen': return ['report.epub']
    return []


def launcher(directory, stage, command, prepared):
    paths = [str(directory/name) for name in stage_inputs(stage, prepared)]
    return ('import hashlib,json,os,stat\nfrom pathlib import Path\n'
        + f'paths={paths!r}\ncommand={command!r}\nbindings={{}}\n'
        + 'for name in paths:\n'
        + '    fd=os.open(name,os.O_RDONLY|getattr(os,"O_NOFOLLOW",0)|getattr(os,"O_NONBLOCK",0))\n'
        + '    with os.fdopen(fd,"rb") as stream:\n'
        + f'        info=os.fstat(stream.fileno())\n        if not stat.S_ISREG(info.st_mode) or info.st_size>{MAX_BYTES}: raise ValueError("invalid native report input")\n'
        + f'        data=stream.read({MAX_BYTES+1})\n        if len(data)>{MAX_BYTES}: raise ValueError("report input limit")\n'
        + '    bindings[name]=hashlib.sha256(data).hexdigest()\n'
        + f'Path({str(directory/(stage+"-inputs.json"))!r}).write_text(json.dumps(bindings,sort_keys=True))\n'
        + 'os.execvpe(command[0],command,os.environ)\n')


def launch(directory, stage, command, prepared, deadline):
    script=directory/(stage+'-launcher.py');script.write_text(launcher(directory,stage,command,prepared))
    try: execute([sys.executable,str(script)],directory,stage,deadline-time.monotonic(),{'LANG':'C.UTF-8'})
    except SchemaxisError as error:
        stderr=str(error.fault.observed.get('stderr',''))
        if 'Could not find data file' in stderr:
            fail('UNSUPPORTED_NATIVE_BUILD','this Pandoc build cannot write the closed report under --sandbox because its default data files '
                 'are not embedded (typical of distribution packages); select the official self-contained Pandoc binary. '
                 'The route never relaxes the sandbox or reads a user/system data directory',stage,stage=stage,stderr=stderr[:400])
        raise


def transcript_observations(directory, prepared):
    """What each captured reviewed/2 or reviewed/3 transcript actually publishes, from the validated retained view; machine drafts and reviewed/1 add none.

    The plan's transcript-loss sentence is not rewritten (existing plans stay identical) and always names one table; a reviewed/2
    document whose cues were all deleted publishes none, so the summary states the actual shape. The text is a statement of
    the validated document's own counts, not an authentication of its mapping to a machine draft.
    """
    observations = []
    for i, j, _ in transcript_blocks(prepared):
        view = retained_transcript(directory, i, j)
        if view['source'] not in (timed_text.REVIEWED2_VERSION, timed_text.REVIEWED3_VERSION): continue
        review = view['review']; kept = len(view['cues']); plural = lambda n: f'{n} cue{"" if n == 1 else "s"}'
        shape = ('one three-column table of the retained cues follows the provenance paragraph' if kept else
                 'no table is published, only the provenance paragraph, so the plan transcript-loss sentence naming one three-column table does not describe this transcript')
        if view['source'] == timed_text.REVIEWED3_VERSION:
            n = review['timingEditCount']
            timing = ('no cue times are shown' if not kept else
                      f'{plural(n)} with author-edited times (source cue indexes {", ".join(map(str, review["timingEditedIndices"]))}), '
                      f'recorded in this document as the author\'s times and not as the machine draft\'s' if n else
                      'no cue times edited by the author; the times shown are those recorded in this document as the machine draft\'s originals')
            observations.append(f'$.sections[{i}].content[{j}]: {timed_text.REVIEWED3_VERSION}; {review["deletionCount"]} of {review["sourceCueCount"]} source cues deleted by the author; '
                                f'{timing}; {plural(kept)} retained; {shape}')
            continue
        observations.append(f'$.sections[{i}].content[{j}]: {timed_text.REVIEWED2_VERSION}; {review["deletionCount"]} of {review["sourceCueCount"]} source cues deleted by the author; '
                            f'{plural(kept)} retained; {shape}')
    return observations


def inspect(directory, prepared):
    from .inspection import html_report, docx_report, ast_report
    model = expected({**prepared, '_directory': directory})
    metadata = prepared.get('metadata')
    html_report(bounded(directory/'report.html').decode(), prepared['title'], model, metadata)
    docx_report(bounded(directory/'report.docx'), prepared['title'], model, metadata)
    ast_report(read(directory,'reopened.json'), directory, prepared['title'], model, metadata)
    summary = {'title': prepared['title'], 'sections': len(prepared['sections']), 'blocks': len(model),
               'tables': sum(b['kind']=='table' for b in model), 'images': sum(b['kind']=='image' for b in model), 'losses': prepared['losses']}
    transcripts = sum(b['kind']=='transcript' for s in prepared['sections'] for b in s['content'])
    if transcripts: summary['transcripts'] = transcripts
    observations = transcript_observations(directory, prepared)
    if observations: summary['transcriptObservations'] = observations
    formats = [b.get('timeFormat') for s in prepared['sections'] for b in s['content'] if b['kind']=='transcript']
    if any(formats): summary['transcriptTimeFormats'] = [f or 'milliseconds' for f in formats]
    if 'epub' in prepared:
        from . import epub
        language = prepared['epub']['language']
        facts = epub.package_report(bounded(directory/'report.epub', limit=epub.MAX_PACKAGE_BYTES), prepared['title'], language, model, metadata)
        epub.readback_report(read(directory, 'epub-reopened.json'), prepared['title'], language, facts, model, metadata)
        summary['epub'] = {'language': language, 'chapters': facts['chapters'], 'entries': facts['entries'], 'mediaFiles': len(facts['media'])}
    if metadata:
        # What was declared and in which publications it was read back; the text itself is in captures.json and the plan.
        summary['metadata'] = {'authors': len(metadata.get('authors', [])), 'description': 'description' in metadata,
                               'characters': metadata_text(metadata), 'formats': ['html', 'docx', *(['epub'] if 'epub' in prepared else [])]}
    return summary


def run(document, directory, *, executable=None, timeout=300):
    prepared = plan(document)
    executable = executable or os.environ.get('SCHEMAXIS_PANDOC') or shutil.which('pandoc')
    if not executable or not Path(executable).is_absolute() or not os.access(executable,os.X_OK):
        fail('INTERPRETER_NOT_FOUND', 'configure an absolute Pandoc executable')
    if type(timeout) not in (int,float) or not math.isfinite(timeout) or not 0 < timeout <= 3600:
        fail('INVALID_ARGUMENT', 'timeout must be finite and in (0,3600]')
    directory = Path(directory).absolute()
    if directory.exists() or directory.is_symlink(): fail('OUTPUT_EXISTS', 'select a fresh report directory', str(directory))
    try: directory.mkdir(parents=True)
    except FileExistsError: fail('OUTPUT_EXISTS','select a fresh report directory',str(directory))
    atomic_json(directory/'authored.json',document); atomic_json(directory/'plan.json',prepared)
    atomic_json(directory/'result.json',{'status':'incomplete','verified':False}); deadline=time.monotonic()+timeout
    try:
        captured={}; captured_bytes=0
        for i,j,block in image_blocks(prepared):
            data=bounded(block['source'],'INVALID_REPORT_IMAGE',4*1024*1024); captured_bytes+=len(data)
            if captured_bytes>8*1024*1024: fail('REPORT_RESOURCE_LIMIT','combined captured PNG bytes exceed8MiB','$.sections')
            name=f'image-{i}-{j}.png'
            captured[name]={'source':block['source'],**png(data,block['source'])}; (directory/name).write_bytes(data)
        views=[]
        for i,j,block in transcript_blocks(prepared):
            where=f'$.sections[{i}].content[{j}]'; name=f'transcript-{i}-{j}.json'
            data=read_source(block['segments']['path'],where+'.segments.path')
            view=transcript_view(data,where+'.segments',block['segments'].get('sha256')); views.append(view)
            captured[name]=transcript_summary(block,view); (directory/name).write_bytes(data)
        if sum(len(v['cues']) for v in views)>timed_text.MAX_CUES: fail('REPORT_RESOURCE_LIMIT',f'a report permits at most {timed_text.MAX_CUES} transcript cues in total; publish further transcripts in another report','$.sections')
        published=[transcript_content(v,b.get('timeFormat')) for v,(_,_,b) in zip(views,transcript_blocks(prepared))]
        if authored_characters(prepared)+sum(len(p)+sum(len(x) for x in c)+sum(len(x) for r in rows for x in r) for p,c,rows in published)>65536:
            fail('REPORT_RESOURCE_LIMIT','report text including transcripts exceeds 65536 characters; publish further transcripts in another report','$.sections')
        atomic_json(directory/'captures.json',{**captured,**({'metadata':metadata_capture(prepared['metadata'])} if 'metadata' in prepared else {})}); (directory/'empty.txt').write_text(''); (directory/'native-data').mkdir()
        native=commands(str(executable),prepared.get('epub'))
        for stage in ('version','api'):
            launch(directory,stage,native[stage],prepared,deadline)
        api=read(directory,'api.json')['pandoc-api-version']
        atomic_json(directory/'report-input.json',ast(prepared,api,directory))
        for stage in ('html','docx','reopen',*(('epub','epubreopen') if 'epub' in prepared else ())):
            launch(directory,stage,native[stage],prepared,deadline)
        summary=inspect(directory,prepared); atomic_json(directory/'report-summary.json',summary)
        names=['authored.json','plan.json','captures.json','empty.txt','api.json','report-input.json','reopened.json']
        if 'epub' in prepared: names.append('epub-reopened.json')
        names += list(captured)
        for stage in native: names += [stage+'-launcher.py',stage+'-inputs.json',stage+'-submission.json',stage+'.stdout',stage+'.stderr']
        names += sorted(str(p.relative_to(directory)) for p in (directory/'reopened').rglob('*') if p.is_file()) if (directory/'reopened').exists() else []
        atomic_json(directory/'verification.json',{'artifacts':artifacts(directory,'epub' in prepared),'evidence':{name:digest(directory,name) for name in names},
                    'executable':str(executable),'runtime':bounded(directory/'version.stdout').decode().splitlines()[0]})
        result=verify(directory,require_result=False)
        if cancellation_requested(): fail('RUNNER_CANCELLED','report publication cancelled')
        if time.monotonic()>=deadline: fail('RUNNER_TIMED_OUT','report exhausted its total deadline')
        result['status']='succeeded'; atomic_json(directory/'result.json',result); return result
    except Exception as error:
        if not isinstance(error,SchemaxisError):
            try: fail('NATIVE_EXECUTION_FAILED',str(error))
            except SchemaxisError as wrapped: error=wrapped
        atomic_json(directory/'result.json',{'status':'failed','verified':False,'fault':error.fault.to_dict()}); raise error


def same_plan(stored,prepared):
    """True when the stored plan is the re-planned report exactly (`'current'`), or carries only the earlier transcript loss text (`'earlier'`)."""
    if stored==prepared: return 'current'
    losses=prepared.get('losses'); earlier=isinstance(losses,list) and losses[-1:]==[TRANSCRIPT_LOSS]
    return 'earlier' if earlier and stored=={**prepared,'losses':[*losses[:-1],LEGACY_TRANSCRIPT_LOSS]} else None


def retained_plan(stored,prepared,views):
    """The plan `verify` replays: the re-planned report, or for a run written with the earlier transcript wording, that run's stored losses.

    The earlier sentence says the status is always machine-draft, so it is accepted only when every captured transcript is a machine draft;
    the report summary then keeps the losses the run was written with."""
    wording=same_plan(stored,prepared)
    if not wording: fail('VERIFICATION_FAILED','effective report plan differs')
    if wording=='current': return prepared
    if not views or any(v['source']!=timed_text.SOURCE_VERSION for v in views):
        fail('VERIFICATION_FAILED','the earlier transcript loss wording (status always machine-draft) is accepted only when every captured transcript is a machine draft','plan.json')
    return {**prepared,'losses':stored['losses']}


def earlier_cue_prepared(prepared,wording,views,stored_input,api,directory):
    """The plan `verify` replays for the cue-count grammar: the current one, or for a run written with the earlier "1 cues" grammar, that grammar.

    Recognised only when the stored plan carries the earlier transcript loss wording that run was written with, only for one-cue machine
    drafts without timeFormat or segmentation, and only when the stored AST is exactly the earlier-grammar AST. Nothing is rewritten; any
    other difference still fails the AST comparison."""
    if wording!='earlier' or stored_input==ast(prepared,api,directory): return prepared
    positions=frozenset((i,j) for (i,j,block),view in zip(transcript_blocks(prepared),views) if legacy_cue_grammar(block,view))
    return {**prepared,'_earlierCues':positions} if positions else prepared


def verify(directory,require_result=True):
    directory=Path(directory).absolute()
    try:
        prepared=plan(read(directory,'authored.json'),retained=True); receipt=read(directory,'verification.json')
        if not isinstance(receipt.get('executable'),str) or not Path(receipt['executable']).is_absolute(): fail('VERIFICATION_FAILED','native executable identity must be absolute')
        stored=read(directory,'plan.json')
        wording=same_plan(stored,prepared)
        if not wording: fail('VERIFICATION_FAILED','effective report plan differs')
        if require_result and read(directory,'result.json').get('status')!='succeeded': fail('INCOMPLETE_EXECUTION','report did not complete')
        data_dir=directory/'native-data'
        if data_dir.is_symlink() or not data_dir.is_dir() or any(data_dir.iterdir()): fail('VERIFICATION_FAILED','isolated native data directory differs')
        captures=read(directory,'captures.json'); names=set(); captured_bytes=0; views=[]
        for i,j,block in image_blocks(prepared):
            name=f'image-{i}-{j}.png'; names.add(name)
            data=bounded(directory/name,limit=4*1024*1024);captured_bytes+=len(data)
            if captured_bytes>8*1024*1024: fail('VERIFICATION_FAILED','combined captured image byte limit exceeded')
            if captures.get(name)!={'source':block['source'],**png(data,name)}:
                fail('VERIFICATION_FAILED','captured image/source binding differs',name)
        for i,j,block in transcript_blocks(prepared):
            name=f'transcript-{i}-{j}.json'; names.add(name)
            data=bounded(directory/name,limit=timed_text.MAX_DOCUMENT_BYTES)
            try: view=transcript_view(data,f'$.sections[{i}].content[{j}].segments',block['segments'].get('sha256'))
            except SchemaxisError as error:
                fail('VERIFICATION_FAILED','captured transcript no longer satisfies the timed-text contract or its pin: '+error.fault.code,name)
            if captures.get(name)!=transcript_summary(block,view): fail('VERIFICATION_FAILED','captured transcript/source binding differs',name)
            views.append(view)
        prepared=retained_plan(stored,prepared,views)
        if set(captures)!=names|({'metadata'} if 'metadata' in prepared else set()): fail('VERIFICATION_FAILED','image, transcript and metadata capture membership differs')
        if 'metadata' in prepared and captures['metadata']!=metadata_capture(prepared['metadata']): fail('VERIFICATION_FAILED','captured metadata record differs from the declared metadata','captures.json')
        api=read(directory,'api.json')['pandoc-api-version']
        stored_input=read(directory,'report-input.json')
        prepared=earlier_cue_prepared(prepared,wording,views,stored_input,api,directory)
        if bounded(directory/'empty.txt') or stored_input!=ast(prepared,api,directory):
            fail('VERIFICATION_FAILED','trusted AST differs from authored report')
        for stage,command in commands(receipt['executable'],prepared.get('epub')).items():
            submission=read(directory,stage+'-submission.json')
            interpreter=submission.get('interpreter',{}).get('executable')
            script=directory/(stage+'-launcher.py')
            if not isinstance(interpreter,str) or not Path(interpreter).is_absolute() or submission.get('nativeCommand')!=[interpreter,str(script)] or type(submission.get('exitCode'))is not int or submission['exitCode']!=0:
                fail('VERIFICATION_FAILED','native command/completion differs',stage)
            if bounded(script).decode()!=launcher(directory,stage,command,prepared): fail('VERIFICATION_FAILED','trusted native launcher differs',stage)
            if read(directory,stage+'-inputs.json')!={str(directory/name):digest(directory,name) for name in stage_inputs(stage,prepared)}:
                fail('VERIFICATION_FAILED','native stage consumed different report input bytes',stage)
        runtime=bounded(directory/'version.stdout').decode().splitlines()[0]
        if not re.fullmatch(r'pandoc \d+\.\d+(?:\.\d+){0,2}',runtime) or receipt['runtime']!=runtime:
            fail('VERIFICATION_FAILED','Pandoc runtime identity differs')
        summary=inspect(directory,prepared)
        if read(directory,'report-summary.json')!=summary: fail('VERIFICATION_FAILED','report summary differs')
        if receipt['artifacts']!=artifacts(directory,'epub' in prepared): fail('VERIFICATION_FAILED','publication membership/digest differs')
        required={'authored.json','plan.json','captures.json','empty.txt','api.json','report-input.json','reopened.json',*names}
        if 'epub' in prepared: required.add('epub-reopened.json')
        for stage in commands(receipt['executable'],prepared.get('epub')): required.update((stage+'-launcher.py',stage+'-inputs.json',stage+'-submission.json',stage+'.stdout',stage+'.stderr'))
        reopened=read(directory,'reopened.json')
        media={b['c'][0]['c'][2][0] for b in reopened['blocks'] if b['t'] in ('Para','Plain') and len(b['c'])==1 and b['c'][0]['t']=='Image'}
        required.update(media)
        if required!=set(receipt['evidence']): fail('VERIFICATION_FAILED','native evidence membership differs')
        members(directory,required|{Path(a['file']).name for a in receipt['artifacts']},'epub' in prepared)
        for name in required:
            if Path(name).is_absolute() or '..' in Path(name).parts or digest(directory,name)!=receipt['evidence'][name]:
                fail('VERIFICATION_FAILED','retained native evidence differs',name)
        return {'verified':True,'artifacts':4 if 'epub' in prepared else 3,'runtime':runtime,**{k:summary[k] for k in ('sections','blocks','tables','images','transcripts','transcriptTimeFormats','epub','metadata') if k in summary}}
    except SchemaxisError: raise
    except Exception as error:
        # Hostile retained bytes must never escape as raw RecursionError, zlib/ZIP, arithmetic or runtime errors.
        fail('VERIFICATION_FAILED','invalid retained report evidence: '+type(error).__name__+': '+str(error)[:200])


from schemaxis.adaptor_runtime import bind as _bind_runtime
_bind_runtime(globals())
