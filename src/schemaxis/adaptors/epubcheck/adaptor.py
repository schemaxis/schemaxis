"""Bounded EPUBCheck standards check of one local EPUB, verified by a fresh native check of the held bytes.

``validate`` captures one local ``.epub``, preflights the ZIP container on the host (size, member count, safe
unique names, no encryption, symlinks, UTF-8/UTF-16 XML text, no entity declarations, only the checker's local DTD catalogue, bounded expansion), and asks the trusted
official EPUBCheck to check the captured bytes with zero tolerated fatal, error or warning findings. Every native stage starts
with the checker's own offline property (``-Depubcheck.offline=true``) fixed in a minimal environment. EPUBCheck is the
standards authority: the host never reads EPUB content semantically. A rejected publication is a checker verdict
(``EPUBCHECK_REJECTED``) and publishes nothing; an accepted one publishes the native JSON assessment and a host summary.
Verification re-runs the separately configured trusted EPUBCheck on the held captured bytes and compares every stable
assessment field. Receipts never supply an executable.
"""
import hashlib
import io
import json
import math
import os
from pathlib import Path
import posixpath
import re
import stat
import sys
import tempfile
from urllib.parse import unquote
from xml.etree import ElementTree
import zipfile

from schemaxis.artifacts import atomic_json
from schemaxis.configuration import executable as configured_executable
from schemaxis.core.declarations import validate_arguments
from schemaxis.core.faults import SchemaxisError
from schemaxis.dispatch import execution_deadline, remaining_timeout
from schemaxis.errors import fail, keys
from schemaxis.native_command import execute

VERSION = 'schemaxis.epubcheck/1'
OPERATIONS = ('validate',)
PLAN_VERSION = 'schemaxis.epubcheck.plan/1'
SUMMARY_VERSION = 'schemaxis.epubcheck.summary/1'
MAX_EPUB_BYTES = 32 * 1024 * 1024
MAX_UNCOMPRESSED_BYTES = 64 * 1024 * 1024
MAX_MEMBER_BYTES = 32 * 1024 * 1024
MAX_MEMBERS = 2000
MAX_NAME_BYTES = 512
INDEX_CHUNK_CHARS = 64 * 1024            # characters handed to the incremental XML index parser at a time
MAX_INDEX_MEMO = 4096                    # distinct rootfile spellings remembered to skip repeats; beyond it a repeat is merely resolved again
RATIO_FLOOR = 256 * 1024                 # members smaller than this are exempt from the expansion-ratio guard
MAX_RATIO = 200
MAX_REPORT_BYTES = 8 * 1024 * 1024
MAX_LOG_BYTES = 1024 * 1024
OUTPUT_SLACK = 64 * 1024
STAGE_TIMEOUT = 180
VERIFY_TIMEOUT = 300
CPU_SECONDS = 2 * STAGE_TIMEOUT + 20     # two JVM threads
MAX_CPUS = 2
CAPTURE = 'captured.epub'
ASSESSMENT = 'assessment.json'
REJECTED = 'rejected-assessment.json'
SUMMARY = 'epubcheck-summary.json'
CHECK_ARGUMENTS = ['--json', ASSESSMENT, '--failonwarnings', '--quiet', '--maxOfEachMessage', 'unlimited', '--locale', 'en']
IDENTITY = re.compile(r'EPUBCheck v5\.4\.0\n?')      # the one audited release; a later patch needs its own catalogue, property and source re-check
VOLATILE = ('checkDate', 'elapsedTime')
SEVERITIES = ('FATAL', 'ERROR', 'WARNING', 'INFO', 'USAGE')
XML_MEDIA_TYPES = frozenset(('application/xhtml+xml', 'application/xml', 'text/xml', 'text/html', 'text/x-oeb1-document', 'application/x-dtbncx+xml',
                             'application/x-dtbook+xml', 'application/smil+xml', 'application/oebps-package+xml', 'image/svg+xml'))
CONTAINER_XML = 'META-INF/container.xml'
MARKERS = (b'<!doctype', b'<!entity')
XML_SUFFIXES = ('.xhtml', '.html', '.htm', '.opf', '.xml', '.ncx', '.svg', '.smil', '.xsl')
OFFLINE_PROPERTY = '-Depubcheck.offline=true'
NATIVE_ENVIRONMENT = {'LANG': 'C.UTF-8', 'LC_ALL': 'C.UTF-8', 'JAVA_TOOL_OPTIONS': OFFLINE_PROPERTY}
OFFLINE_NOTICE = 'Picked up JAVA_TOOL_OPTIONS: %s\n' % OFFLINE_PROPERTY      # the JVM's own stderr line; the only stderr a quiet stage may carry
# 14 of the 15 http identifiers (the 15th is an upstream typo, safely left out) that EPUBCheck 5.4.0 resolves from its own jar (DefaultResolver.SYSTEM_ID_MAP, sha256 ee940cd22f1b5b38d95f098668068f07c96bebfe49e3a45a09b3e844cf29a104)
# plus the HTML5 legacy-compat identifier it answers with an empty entity. Any other SYSTEM identifier could reach a fetch fallback, so the host refuses it.
CATALOGUE_DTDS = frozenset((
    'http://openebook.org/dtds/oeb-1.2/oebpkg12.dtd', 'http://openebook.org/dtds/oeb-1.2/oeb12.ent', 'http://openebook.org/dtds/oeb-1.2/oebdoc12.dtd',
    'http://www.idpf.org/dtds/2007/opf.dtd', 'http://www.w3.org/TR/xhtml1/DTD/xhtml1-transitional.dtd', 'http://www.w3.org/TR/xhtml1/DTD/xhtml1-strict.dtd',
    'http://www.w3.org/TR/xhtml1/DTD/xhtml-lat1.ent', 'http://www.w3.org/TR/xhtml1/DTD/xhtml-symbol.ent', 'http://www.w3.org/TR/xhtml1/DTD/xhtml-special.ent',
    'http://www.w3.org/Graphics/SVG/1.1/DTD/svg11.dtd', 'http://www.daisy.org/z3986/2005/dtbook-2005-2.dtd', 'http://www.daisy.org/z3986/2005/ncx-2005-1.dtd',
    'http://www.w3.org/TR/xhtml11/DTD/xhtml11.dtd', 'http://www.w3.org/MarkUp/DTD/xhtml11.dtd', 'about:legacy-compat'))
LITERAL = r'(?:"[^"]*"|\'[^\']*\')'
DOCTYPE_FORM = re.compile(r'<!DOCTYPE[ \t\r\n]+[^\s<>\[\]"\'&%%]+(?:[ \t\r\n]+(?:PUBLIC[ \t\r\n]+%s[ \t\r\n]+(%s)|SYSTEM[ \t\r\n]+(%s)))?[ \t\r\n]*>' % (LITERAL, LITERAL, LITERAL))
XML_DECLARATION = re.compile(r'<\?xml[ \t\r\n][^>]*?\?>')
DECLARED_ENCODING = re.compile(r'[ \t\r\n]encoding[ \t\r\n]*=[ \t\r\n]*(?:"([^"]*)"|\'([^\']*)\')')
UTF32_MARKS = (b'\xff\xfe\x00\x00', b'\x00\x00\xfe\xff', b'\x00\x00\xff\xfe', b'\xfe\xff\x00\x00', b'\x00\x00\x00<', b'<\x00\x00\x00', b'\x00\x00<\x00', b'\x00<\x00\x00')
SOURCE_FAULTS = ('INVALID_EPUB_SOURCE', 'INVALID_EPUB_ARCHIVE', 'UNSAFE_EPUB_ARCHIVE', 'UNSUPPORTED_EPUB_FEATURE', 'EPUB_BUDGET')
RUNTIME_FAILURES = ((re.compile(r'OutOfMemoryError|Could not reserve|insufficient memory|Cannot allocate memory', re.I), 'NATIVE_RESOURCE_EXHAUSTED'),
                    (re.compile(r'Could not find or load main class|Unable to access jarfile|NoClassDefFoundError|UnsatisfiedLinkError|ClassNotFoundException|'
                                r'Error occurred during initialization|No such file or directory|not found|Permission denied', re.I), 'NATIVE_UNAVAILABLE'))

OPTIONS = {'source': {'type': 'string', 'minLength': 1, 'maxLength': 4096, 'required': True}}
DECLARATIONS = {'validate': {
    'native': 'epubcheck captured.epub --json assessment.json --failonwarnings --quiet --maxOfEachMessage unlimited --locale en '
              '(official EPUBCheck 5.4.0 distribution through a configured fixed launcher); no profile, mode, custom-message or severity options',
    'kinds': ['file', 'text'], 'inputs': {}, 'options': {k: {'value': v} for k, v in OPTIONS.items()}}}
LOSSES = [
    'One absolute local EPUB (a ZIP file starting with a local file header) of at most 32 MiB, 2000 members, 64 MiB uncompressed (32 MiB per member). Encrypted members, symbolic links, unsafe, duplicate or case-colliding member names, non-ASCII member names without the ZIP UTF-8 flag, compression other than stored/deflated, extreme expansion ratios and unreadable members are refused before any native process starts. So are XML members that are not strictly decodable UTF-8 or byte-order-marked UTF-16 (UTF-32, UTF-16 without a mark, EBCDIC, NUL characters, malformed text and other declared encodings), that declare an XML entity or an internal DTD subset, or whose DOCTYPE names a SYSTEM identifier outside 14 of the 15 http identifiers EPUBCheck 5.4.0 resolves from its own jar and about:legacy-compat. The XML members are those with the extensions .xhtml, .html, .htm, .opf, .xml, .ncx, .svg, .smil or .xsl, the rootfiles of META-INF/container.xml and the package manifest items whose declared media type is XML, under any file name; as a backstop that does not depend on the index finding a name, any other member whose first bytes look like XML (a UTF-32/UCS-4 byte-order mark or less-than-sign pattern in any byte order, the EBCDIC signature of the text <?xm, or a <?xml prefix with or without a UTF-8 mark, in any case) is held to the same profile, so UCS-4, EBCDIC and declared non-UTF-8 encodings are refused, and any other member that contains DOCTYPE or ENTITY text in ASCII/UTF-8 or UTF-16 is held to it too while the same text in UTF-32 is refused. The host refuses a backslash or control character (C0, tab, CR, LF, DEL, including those written as XML character references) in a rootfile full-path or the href of a manifest item declared as XML, and a ZIP member name containing a NUL byte, because path and URL resolution could disagree about them; it does not implement a general URL parser. A container or package document the host cannot parse as XML is refused. This is a bounded host index of the container and manifest, not an EPUB reader, and not a claim to know every encoding the checker parser could detect: it refuses the signatures it recognises, and it is not an operating-system network or file boundary. Expanded (unzipped) EPUB directories and single OPF/XHTML files are not supported.',
    'The checker runs the default EPUB profile only, with --failonwarnings: the publication is accepted only when EPUBCheck reports zero fatal, error and warning messages and exits 0. Dictionary, EDUPUB, index and preview profiles, custom message severities, suppressions, usage reports and other flags are not authorable. Informational and usage-level messages do not reject but are listed.',
    'Every native stage (version, check and the fresh check of verification) starts the launcher in a minimal environment whose only Java setting is the fixed JAVA_TOOL_OPTIONS=-Depubcheck.offline=true; the caller\'s JAVA_TOOL_OPTIONS, JDK_JAVA_OPTIONS and _JAVA_OPTIONS are not inherited. That is the official checker\'s own property for turning off its default online fetch of an unknown EPUB 2 external http DTD. It is not an operating-system network boundary: a launcher could ignore it, it does not cover other schemes (a jar:http: identifier was observed fetched under it) and it does not stop the checker reading a local file named by a file: URL; the host refuses every DOCTYPE SYSTEM identifier outside the catalogue in the members it holds to the XML profile. The version stage must show the JVM notice \'Picked up JAVA_TOOL_OPTIONS: -Depubcheck.offline=true\' as its whole stderr, otherwise the run is refused as an unsupported runtime; that notice, and the same exact stderr and empty stdout from every quiet check stage including the fresh check, is the only native output accepted. The host sets no memory limit: the Java heap bound is the configured trusted launcher\'s own option, and the 8 MiB report cap is a kernel file-size cap plus one byte that detects a truncated report as resource exhaustion.',
    'EPUBCheck is the standards authority; the host adds only container preflight and consistency checks of the native JSON report (closed typed schema, message counts equal counters, report items equal the container files). It does not validate content, render the book, run scripts or test on a device or reading system.',
    'A publication the checker rejects publishes nothing: the run fails with EPUBCHECK_REJECTED and the native findings are retained as rejected-assessment.json evidence in the run directory.',
    'Zero findings is a scoped tool result from one EPUBCheck release. It is not a guarantee of correct rendering, reading-system compatibility, legal or accessibility certification, or authenticity of the publication.',
    'Verification re-runs the separately configured trusted launcher on the held captured bytes and compares every stable assessment field. Only checker.checkDate and checker.elapsedTime are excluded because they differ between runs. The captured file is a writable, unauthenticated copy, not signed history.']


# ---------------------------------------------------------------- planning
def plan(document):
    keys(document, ('version', 'operation', *OPTIONS), '$')
    if document.get('version') != VERSION:
        fail('UNSUPPORTED_VERSION', 'expected ' + VERSION)
    operation = document.get('operation')
    if not isinstance(operation, str) or operation not in OPERATIONS:
        fail('UNKNOWN_FILTER', 'select validate', '$.operation')
    prepared = validate_arguments(OPTIONS, {k: v for k, v in document.items() if k in OPTIONS})
    source = prepared['source']
    if '\0' in source or not Path(source).is_absolute() or Path(source).suffix.lower() != '.epub':
        fail('INVALID_EPUB_SOURCE', 'select an absolute local regular .epub file; no URLs, directories or relative paths', '$.source')
    native = {'arguments': ['epubcheck', CAPTURE, *CHECK_ARGUMENTS], 'policy': 'zero fatal, error and warning messages (--failonwarnings)',
              'profile': 'default',
              'network': 'epubcheck.offline=true through a fixed JAVA_TOOL_OPTIONS in every native stage; the checker\'s own switch for unknown EPUB 2 http DTD fetches, not an operating-system network boundary; the host refuses non-catalogue DOCTYPE SYSTEM identifiers in every XML member',
              'environment': {'JAVA_TOOL_OPTIONS': OFFLINE_PROPERTY}}
    return {'version': PLAN_VERSION, 'operation': operation, **prepared, 'native': native,
            'budget': {'maxEpubBytes': MAX_EPUB_BYTES, 'maxUncompressedBytes': MAX_UNCOMPRESSED_BYTES, 'maxMemberBytes': MAX_MEMBER_BYTES,
                       'maxMembers': MAX_MEMBERS, 'maxReportBytes': MAX_REPORT_BYTES, 'cpus': MAX_CPUS, 'stageSeconds': STAGE_TIMEOUT},
            'losses': LOSSES}


def schema():
    from schemaxis.schema import DRAFT, argument_schema, object_schema
    properties = {'version': {'const': VERSION}, 'operation': {'const': 'validate'}, **{k: argument_schema(v) for k, v in OPTIONS.items()}}
    return {'$schema': DRAFT, **object_schema(properties, ['version', 'operation', 'source'])}


def query(document):
    return [plan(document)['operation']], {}


def resources(document, execution, identity):
    threads = execution.get('threads', MAX_CPUS)
    if type(threads) is not int or not 1 <= threads <= MAX_CPUS:
        fail('INVALID_EXECUTION', 'EPUBCheck runs on at most %d threads' % MAX_CPUS, identity)
    return {'threads': threads}


# ---------------------------------------------------------------- bounded host inputs and strict JSON
def bounded(path, code='VERIFICATION_FAILED', limit=MAX_EPUB_BYTES, location=None):
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


def digest(directory, name, limit=MAX_EPUB_BYTES, held=None):
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


def strict_json(data, name, code='VERIFICATION_FAILED'):
    """Strict UTF-8 JSON: no byte-order mark, duplicate keys, NaN/Infinity, numbers that overflow to infinity or excess depth."""
    try:
        text = data.decode('utf-8')
        if text.startswith('﻿'):
            raise ValueError('byte-order mark')
        return json.loads(text, object_pairs_hook=unique_object, parse_float=finite_number, parse_constant=refuse_constant)
    except (ValueError, UnicodeError, RecursionError) as error:
        fail(code, 'invalid JSON %s: %s' % (name, str(error)[:80]))


def read_json(directory, name):
    return strict_json(bounded(Path(directory) / name, limit=MAX_LOG_BYTES), name)


def same_json(actual, expected):
    """Typed canonical comparison: 1 is not true and 66 is not 66.0, unlike Python equality."""
    try:
        return json.dumps(actual, sort_keys=True, allow_nan=False) == json.dumps(expected, sort_keys=True, allow_nan=False)
    except (ValueError, TypeError, RecursionError):
        return False


# ---------------------------------------------------------------- container preflight (resource and unsafe-profile bounds only)
def safe_name(name):
    if not name or len(name.encode('utf-8', 'replace')) > MAX_NAME_BYTES or any(ord(c) < 32 or ord(c) == 127 for c in name) or '\\' in name:
        return False
    if name.startswith('/') or re.match(r'^[A-Za-z]:', name):
        return False
    parts = name[:-1].split('/') if name.endswith('/') else name.split('/')
    return all(part not in ('', '.', '..') for part in parts)


def xml_text(name, data, location):
    """Decode one XML member under the supported profile: UTF-8 (optional BOM) or UTF-16 with a byte-order mark, strictly.

    UTF-32/UCS-4, UTF-16 without a mark, NUL characters, malformed text and any declared encoding other than UTF-8 (or UTF-16 under a UTF-16 mark)
    are refused, so the entity and DOCTYPE scan below always reads the text the checker will read.
    """
    def refuse(why):
        fail('UNSUPPORTED_EPUB_FEATURE', 'member %s %s; only UTF-8 and byte-order-marked UTF-16 XML are supported' % (name, why), location)
    if data[:4] in UTF32_MARKS:
        refuse('is UTF-32 or UCS-4 encoded')
    utf16 = data[:2] in (b'\xff\xfe', b'\xfe\xff')
    body = data if utf16 else data[3:] if data.startswith(b'\xef\xbb\xbf') else data
    if b'\x00' in data and not utf16:
        refuse('contains NUL bytes (UTF-16 without a byte-order mark or binary data)')
    try:
        text = body.decode('utf-16' if utf16 else 'utf-8')
    except UnicodeDecodeError:
        refuse('is not well-formed %s text' % ('UTF-16' if utf16 else 'UTF-8'))
    if '\x00' in text:
        refuse('contains a NUL character')
    declaration = XML_DECLARATION.match(text)
    declared = DECLARED_ENCODING.search(declaration.group(0)) if declaration else None
    if declared:
        label = (declared.group(1) if declared.group(1) is not None else declared.group(2)).lower()
        if label != ('utf-16' if utf16 else 'utf-8'):
            refuse('declares the encoding %r for %s bytes' % (label[:20], 'UTF-16' if utf16 else 'UTF-8'))
    return text


def scan_xml(name, data, location):
    """Refuse constructs the host will not hand to the checker: entity declarations, internal DTD subsets and any DOCTYPE SYSTEM identifier
    outside the checker's own DTD catalogue (the checker could otherwise fetch it or read a local file named by it)."""
    text = xml_text(name, data, location)
    if re.search(r'<!ENTITY', text, re.I):
        fail('UNSUPPORTED_EPUB_FEATURE', 'member %s declares an XML entity; entity declarations are not supported' % name, location)
    for doctype in re.finditer(r'<!DOCTYPE', text, re.I):
        form = DOCTYPE_FORM.match(text, doctype.start())
        if not form:
            fail('UNSUPPORTED_EPUB_FEATURE', 'member %s has an unsupported DOCTYPE (an internal DTD subset or irregular syntax); only a plain DOCTYPE or '
                 'PUBLIC/SYSTEM names with a catalogue SYSTEM identifier are supported' % name, location)
        literal = form.group(1) or form.group(2)
        if literal is not None and literal[1:-1] not in CATALOGUE_DTDS:
            fail('UNSUPPORTED_EPUB_FEATURE', 'member %s names a DOCTYPE SYSTEM identifier outside the EPUBCheck local DTD catalogue' % name, location)
    return text


MARKER_FORMS = tuple(marker.decode().encode(codec) for marker in MARKERS for codec in ('ascii', 'utf-16-le', 'utf-16-be'))
UTF32_MARKER_FORMS = tuple(marker.decode().encode(codec) for marker in MARKERS for codec in ('utf-32-le', 'utf-32-be'))


EBCDIC_XML_SIGNATURE = b'\x4c\x6f\xa7\x94'      # '<?xm' in every EBCDIC code page (cp037, cp500, cp1047...): the XML spec's own autodetection signature


def looks_like_xml(data):
    """Bytes whose first octets are an XML encoding signature the checker's parser would act on: any UCS-4/UTF-32 byte-order mark or '<' pattern
    (including the mixed 2143 and 3412 orders), the EBCDIC '<?xm' signature, or an ASCII-compatible '<?xml' prefix with or without a UTF-8 byte-order mark
    (any case: the host is conservative). The host does not claim to know every encoding the native parser could detect; it refuses any it recognises here."""
    head = data[3:8] if data.startswith(b'\xef\xbb\xbf') else data[:5]
    return data[:4] in UTF32_MARKS or data[:4] == EBCDIC_XML_SIGNATURE or head.lower() == b'<?xml'


def guard_other_member(name, data, location):
    """Backstop for a member the host did not index as XML, independent of how precisely the index resolves names: a member that looks like XML by its
    first bytes (see looks_like_xml) is held to the strict XML profile whatever its name, which refuses UCS-4, EBCDIC and any declared encoding other
    than UTF-8. Any other member carrying a DOCTYPE or ENTITY marker (ASCII/UTF-8, UTF-16LE or UTF-16BE, any case) is held to the same profile, and a
    UTF-32 marker anywhere is refused as unsupported, never ignored."""
    if looks_like_xml(data):
        scan_xml(name, data, location)
        return
    lowered = data.lower()
    if any(form in lowered for form in UTF32_MARKER_FORMS):
        fail('UNSUPPORTED_EPUB_FEATURE', 'member %s carries UTF-32 or UCS-4 encoded DOCTYPE or ENTITY text; only UTF-8 and byte-order-marked UTF-16 XML are supported' % name, location)
    if any(form in lowered for form in MARKER_FORMS):
        scan_xml(name, data, location)


def media_type_is_xml(value):
    value = value.split(';')[0].strip().lower() if isinstance(value, str) else ''
    return value in XML_MEDIA_TYPES or value.endswith('+xml')


def reference_candidates(reference, base, names):
    """Container members a package-relative reference could name (raw and percent-decoded, with and without fragment/query); safe, never outside the container."""
    reference = reference.strip()
    if not reference or reference.startswith('//') or re.match(r'^[A-Za-z][A-Za-z0-9+.\-]*:', reference):
        return set()
    stripped = reference.split('#')[0].split('?')[0]
    found = set()
    for form in {reference, reference.split('#')[0], stripped}:
        for text in {form, unquote(form, errors='replace')}:
            for origin in (base, ''):
                joined = posixpath.normpath(posixpath.join(origin, text.lstrip('/') if origin == '' else text)) if text else ''
                if joined and not joined.startswith('..') and joined in names:
                    found.add(joined)
    return found


def ambiguous_reference(value):
    """A backslash or a control character (C0, tab, CR, LF, DEL; the value is already decoded, so character references count) makes a package-relative
    reference mean different members to a POSIX-path index and to a URL parser. The host refuses it rather than implement a general URL parser."""
    return '\\' in value or any(ord(c) < 32 or ord(c) == 127 for c in value)


class IndexTarget:
    """Parser target that hands each start tag to a callback without building a per-element tree. The parser still retains open-element nesting and distinct element/attribute names."""
    def __init__(self, element):
        self.element = element

    def start(self, tag, attrib):
        self.element(tag.rsplit('}', 1)[-1], attrib)

    def end(self, tag):
        pass

    def close(self):
        pass


def index_xml(name, text, location, element):
    """Feed one already-scanned document through the standard XML parser in bounded chunks, reading to the end so a malformed tail is always found.
    The parser's own state grows with open-element nesting and distinct element/attribute names, in addition to the current chunk and retained role references. It is input-bounded, not constant-memory; the parser is dropped even when it faults."""
    parser = ElementTree.XMLParser(target=IndexTarget(element))
    try:
        for start in range(0, len(text), INDEX_CHUNK_CHARS):
            parser.feed(text[start:start + INDEX_CHUNK_CHARS])
        parser.close()
    except ElementTree.ParseError as error:
        fail('UNSUPPORTED_EPUB_FEATURE', 'member %s is not well-formed XML for the host manifest index (%s); the checker is not asked to judge it' % (name, str(error)[:60]), location)
    finally:
        del parser


def xml_member_names(read, names, location):
    """Members EPUBCheck parses as XML by role rather than extension: the container's rootfiles and the package manifest items whose declared
    media type is XML. The container and package documents are held to the strict profile before the host parses them; one the host cannot parse
    is refused, because its manifest could not be indexed. Each document is read by an incremental parser without a per-element tree; open-element
    nesting and distinct element/attribute names still consume input-bounded parser state, so this is not a constant-memory or OS heap guarantee.
    The package names of every rootfile are resolved as they stream past (a bounded memo skips repeated
    spellings) and each distinct package is read, decoded and parsed once, so the work is bounded by the container's size and the package count, not by
    the number of rootfile elements. The first ambiguous reference is remembered and refused only after the whole document proved well formed, so a
    malformed document is reported as malformed exactly as before."""
    found = set()
    if CONTAINER_XML not in names:
        return found
    ambiguous = []

    def note_ambiguous(kind, value):
        if not ambiguous and ambiguous_reference(value):
            ambiguous.append((kind, value[:60]))

    def parse(name, element):
        del ambiguous[:]
        index_xml(name, scan_xml(name, read(name), location), location, element)
        if ambiguous:
            fail('UNSUPPORTED_EPUB_FEATURE', '%s %r contains a backslash or a control character; its meaning differs between path and URL resolution, so the host does not index it' % ambiguous[0], location)
    packages, seen = set(), set()

    def rootfile(local, attrib):
        full_path = attrib.get('full-path') if local == 'rootfile' else None
        if full_path:
            note_ambiguous('rootfile full-path', full_path)
            if full_path not in seen:
                if len(seen) < MAX_INDEX_MEMO:
                    seen.add(full_path)
                packages.update(reference_candidates(full_path, '', names))
    parse(CONTAINER_XML, rootfile)
    for package in sorted(packages):
        found.add(package)

        def item(local, attrib, base=posixpath.dirname(package)):
            href = attrib.get('href') if local == 'item' else None
            if href and media_type_is_xml(attrib.get('media-type')):
                note_ambiguous('manifest href', href)
                found.update(reference_candidates(href, base, names))
        parse(package, item)
    return found


def preflight(data, location='$.source'):
    """Bounded safe-profile facts about a ZIP container; the checker, not the host, judges whether it is a conforming EPUB."""
    if len(data) > MAX_EPUB_BYTES:
        fail('EPUB_BUDGET', 'EPUB is larger than %d bytes' % MAX_EPUB_BYTES, location)
    if data[:4] != b'PK\x03\x04':
        fail('INVALID_EPUB_ARCHIVE', 'not an EPUB ZIP container: the file must start with a ZIP local file header', location)
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
        infos = archive.infolist()
        if len(infos) > MAX_MEMBERS:
            fail('EPUB_BUDGET', 'EPUB has %d members; at most %d are supported' % (len(infos), MAX_MEMBERS), location)
        seen, folded, total, members = set(), set(), 0, []
        for info in infos:
            name = info.filename
            if info.orig_filename != name:        # CPython cuts a stored name at its first NUL; Java does not
                fail('UNSAFE_EPUB_ARCHIVE', 'member name %r contains a NUL byte' % info.orig_filename[:80], location)
            if not safe_name(name):
                fail('UNSAFE_EPUB_ARCHIVE', 'unsafe member name %r' % name[:80], location)
            if name in seen or name.casefold() in folded:
                fail('UNSAFE_EPUB_ARCHIVE', 'duplicate or case-colliding member name %r' % name[:80], location)
            if not info.flag_bits & 0x800 and not name.isascii():
                fail('UNSUPPORTED_EPUB_FEATURE', 'member name %r has non-ASCII bytes without the ZIP UTF-8 flag; its encoding is ambiguous between this host and the checker' % name[:80], location)
            seen.add(name)
            folded.add(name.casefold())
            if info.flag_bits & 0x41:
                fail('UNSUPPORTED_EPUB_FEATURE', 'encrypted ZIP member %r is not supported' % name[:80], location)
            kind = (info.external_attr >> 16) & 0o170000 if info.create_system == 3 else 0
            if kind not in (0, stat.S_IFREG, stat.S_IFDIR) or (name.endswith('/') != info.is_dir()):
                fail('UNSAFE_EPUB_ARCHIVE', 'member %r is a symbolic link or special file' % name[:80], location)
            if info.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED):
                fail('UNSUPPORTED_EPUB_FEATURE', 'member %r uses an unsupported compression method' % name[:80], location)
            if info.file_size > MAX_MEMBER_BYTES:
                fail('EPUB_BUDGET', 'member %r expands beyond %d bytes' % (name[:80], MAX_MEMBER_BYTES), location)
            if info.file_size > RATIO_FLOOR and info.file_size > MAX_RATIO * max(info.compress_size, 1):
                fail('EPUB_BUDGET', 'member %r expands more than %d times (compression bomb profile)' % (name[:80], MAX_RATIO), location)
            total += info.file_size
            if total > MAX_UNCOMPRESSED_BYTES:
                fail('EPUB_BUDGET', 'EPUB expands beyond %d bytes' % MAX_UNCOMPRESSED_BYTES, location)
            if not info.is_dir():
                members.append({'name': name, 'compressed': info.compress_size, 'uncompressed': info.file_size,
                                'method': 'Stored' if info.compress_type == zipfile.ZIP_STORED else 'Deflated'})
        by_name = {info.filename: info for info in infos if not info.is_dir()}

        def read(name):
            info = by_name[name]
            with archive.open(info) as stream:
                content = stream.read(info.file_size + 1)       # bounded by the declared size; CRC is checked at end of stream
            if len(content) != info.file_size:
                fail('INVALID_EPUB_ARCHIVE', 'member %r does not expand to its declared size' % name[:80], location)
            return content
        by_role = xml_member_names(read, set(by_name), location)
        for name in by_name:
            content = read(name)
            if name in by_role or name.lower().endswith(XML_SUFFIXES):
                scan_xml(name, content, location)
            else:
                guard_other_member(name, content, location)
        return {'members': members, 'directories': sum(1 for i in infos if i.is_dir()), 'compressedBytes': len(data), 'uncompressedBytes': total}
    except (zipfile.BadZipFile, zipfile.LargeZipFile, NotImplementedError, EOFError, OSError, ValueError, RuntimeError, OverflowError) as error:
        fail('INVALID_EPUB_ARCHIVE', 'unreadable ZIP container: %s' % str(error)[:80], location)


# ---------------------------------------------------------------- closed native report
def is_int(value, low=0):
    return type(value) is int and low <= value <= 1 << 40


def optional_text(value):
    return value is None or (isinstance(value, str) and len(value) <= 65536)


def text_list(value):
    return isinstance(value, list) and len(value) <= 4096 and all(isinstance(v, str) and len(v) <= 65536 for v in value)


PUBLICATION_TYPES = {
    'publisher': optional_text, 'title': optional_text, 'creator': text_list, 'date': optional_text, 'subject': text_list, 'description': optional_text,
    'rights': optional_text, 'identifier': optional_text, 'language': optional_text, 'nSpines': is_int, 'checkSum': is_int, 'renditionLayout': optional_text,
    'renditionOrientation': optional_text, 'renditionSpread': optional_text, 'ePubVersion': optional_text, 'isScripted': lambda v: type(v) is bool,
    'hasFixedFormat': lambda v: type(v) is bool, 'isBackwardCompatible': lambda v: type(v) is bool, 'hasAudio': lambda v: type(v) is bool,
    'hasVideo': lambda v: type(v) is bool, 'charsCount': is_int, 'embeddedFonts': text_list, 'refFonts': text_list,
    'hasEncryption': lambda v: type(v) is bool, 'hasSignatures': lambda v: type(v) is bool, 'contributors': text_list}
ITEM_TYPES = {
    'id': lambda v: isinstance(v, str), 'fileName': lambda v: isinstance(v, str) and bool(v), 'media_type': optional_text, 'compressedSize': is_int,
    'uncompressedSize': is_int, 'compressionMethod': lambda v: v in ('Stored', 'Deflated'), 'checkSum': optional_text,
    'isSpineItem': lambda v: type(v) is bool, 'spineIndex': lambda v: v is None or is_int(v), 'isLinear': lambda v: type(v) is bool,
    'isFixedFormat': lambda v: v is None or type(v) is bool, 'isScripted': lambda v: type(v) is bool, 'renditionLayout': optional_text,
    'renditionOrientation': optional_text, 'renditionSpread': optional_text, 'referencedItems': text_list}
LOCATION_TYPES = {'url': lambda v: isinstance(v, dict) and set(v) == {'opaque', 'hierarchical'} and all(type(x) is bool for x in v.values()),
                  'path': optional_text, 'line': lambda v: type(v) is int and -1 <= v <= 1 << 31, 'column': lambda v: type(v) is int and -1 <= v <= 1 << 31,
                  'context': optional_text}
MESSAGE_TYPES = {'ID': lambda v: isinstance(v, str) and re.fullmatch(r'[A-Z]{2,5}-\d{3}', v) is not None, 'severity': lambda v: v in SEVERITIES,
                 'message': lambda v: isinstance(v, str) and len(v) <= 65536, 'additionalLocations': is_int,
                 'locations': lambda v: isinstance(v, list) and len(v) <= 4096 and all(closed(x, LOCATION_TYPES) for x in v), 'suggestion': optional_text}
CHECKER_TYPES = {'path': lambda v: v == './' + CAPTURE, 'filename': lambda v: v == CAPTURE, 'checkerVersion': lambda v: isinstance(v, str),
                 'checkDate': lambda v: isinstance(v, str) and 0 < len(v) <= 64, 'elapsedTime': is_int, 'nFatal': is_int, 'nError': is_int,
                 'nWarning': is_int, 'nUsage': is_int}


def closed(value, types):
    return isinstance(value, dict) and set(value) == set(types) and all(types[key](value[key]) for key in types)


def parse_report(data, identity, name=ASSESSMENT, code='EPUBCHECK_REPORT_INVALID'):
    """Closed typed parse of a native JSON assessment; messages must agree with the counters and the checker with the identity."""
    report = strict_json(data, name, code)

    def refuse(message):
        fail(code, 'native assessment %s: %s' % (name, message), name)
    if not isinstance(report, dict) or set(report) != {'messages', 'customMessageFileName', 'checker', 'publication', 'items'}:
        refuse('unexpected top-level members')
    if report['customMessageFileName'] is not None:
        refuse('custom message file is not supported')
    if not closed(report['checker'], CHECKER_TYPES):
        refuse('checker block has unexpected members or types')
    if 'EPUBCheck v' + report['checker']['checkerVersion'] != identity.strip():
        refuse('checker version differs from the observed runtime identity')
    if not isinstance(report['messages'], list) or len(report['messages']) > 100000 or not all(closed(m, MESSAGE_TYPES) for m in report['messages']):
        refuse('messages have unexpected members or types')
    counts = {severity: sum(1 for m in report['messages'] if m['severity'] == severity) for severity in SEVERITIES}
    checker = report['checker']
    if (counts['FATAL'], counts['ERROR'], counts['WARNING'], counts['USAGE']) != (checker['nFatal'], checker['nError'], checker['nWarning'], checker['nUsage']):
        refuse('message counts %s differ from the checker counters' % counts)
    if not closed(report['publication'], PUBLICATION_TYPES):
        refuse('publication block has unexpected members or types')
    items = report['items']
    if not isinstance(items, list) or len(items) > MAX_MEMBERS or not all(closed(item, ITEM_TYPES) for item in items):
        refuse('items have unexpected members or types')
    names = [item['fileName'] for item in items]
    if len(set(names)) != len(names):
        refuse('duplicate item file names')
    return report


def stable(report):
    """The assessment without the explicitly nondeterministic checker fields (checkDate, elapsedTime)."""
    return {**report, 'checker': {k: v for k, v in report['checker'].items() if k not in VOLATILE}}


def severity_counts(report):
    checker = report['checker']
    info = sum(1 for m in report['messages'] if m['severity'] == 'INFO')
    return {'fatal': checker['nFatal'], 'error': checker['nError'], 'warning': checker['nWarning'], 'usage': checker['nUsage'], 'info': info}


def bind_items(report, facts, location):
    """Report items against the host's view of the container: the same files with the same sizes and compression."""
    members = {m['name']: m for m in facts['members']}
    items = {item['fileName']: item for item in report['items']}
    if set(items) != set(members):
        fail('EPUBCHECK_REPORT_INVALID', 'report items differ from the container files (%s)' % ', '.join(sorted(set(items) ^ set(members))[:4]), location)
    for name, item in items.items():
        member = members[name]
        if (item['compressedSize'], item['uncompressedSize'], item['compressionMethod']) != (member['compressed'], member['uncompressed'], member['method']):
            fail('EPUBCHECK_REPORT_INVALID', 'report item %s sizes or compression differ from the container' % name, location)
    if any(item['isSpineItem'] and item['spineIndex'] is None for item in report['items']):
        fail('EPUBCHECK_REPORT_INVALID', 'a spine item has no spine index', location)
    spines = sorted(item['spineIndex'] for item in report['items'] if item['isSpineItem'])
    if report['publication']['nSpines'] != len(spines) or spines != list(range(len(spines))):
        fail('EPUBCHECK_REPORT_INVALID', 'spine items do not match nSpines', location)


def clean_message(message):
    path = message['locations'][0]['path'] if message['locations'] else None
    line = message['locations'][0]['line'] if message['locations'] else None
    return {'id': message['ID'], 'severity': message['severity'], 'path': path, 'line': line, 'message': message['message'][:240]}


def findings(report, limit=20):
    ordered = [m for m in report['messages'] if m['severity'] in ('FATAL', 'ERROR', 'WARNING')]
    return {'counts': severity_counts(report), 'messages': [clean_message(m) for m in ordered[:limit]], 'truncated': max(0, len(ordered) - limit)}


# ---------------------------------------------------------------- trusted runtime and fixed native stages
def runtime(executable=None):
    """Trusted launcher: explicit argument, then invocation context/stored configuration, then SCHEMAXIS_EPUBCHECK. Never PATH or a receipt."""
    value = executable or configured_executable('epubcheck') or os.environ.get('SCHEMAXIS_EPUBCHECK')
    if not isinstance(value, str) or not os.path.isabs(value) or not os.path.isfile(value) or not os.access(value, os.X_OK):
        fail('INTERPRETER_NOT_FOUND', 'configure an absolute trusted EPUBCheck 5.4.0 launcher (a fixed executable that starts the official JAR with its lib directory and Java); verification re-checks the held bytes natively',
             '$.runtime.epubcheck', recovery='use --epubcheck, schemaxis configure epubcheck, or SCHEMAXIS_EPUBCHECK (a stored locations.epubcheck entry also works); schemaxis verify takes no --epubcheck flag')
    return {'epubcheck': value}


def launcher(stage, names, command, limit):
    """Fixed trusted launcher: resource, CPU and file caps, bounded input binding, then exec (127 if exec fails) in a minimal environment.

    The file-size cap is the reader budget plus one byte: the JVM ignores SIGXFSZ, so an output that hits the cap is a short write, and only a file
    larger than the budget proves an overflow (``overflowed``) before any JSON or diagnostic is read.

    The environment is exactly ``NATIVE_ENVIRONMENT``: the caller's JAVA_TOOL_OPTIONS, JDK_JAVA_OPTIONS and _JAVA_OPTIONS are never inherited,
    and the checker's offline property is fixed for the identity, check and fresh-check stages alike.
    """
    return ('import hashlib,json,os,stat,resource\nfrom pathlib import Path\n'
            'resource.setrlimit(resource.RLIMIT_FSIZE,(%d,%d))\n' % (limit + 1, limit + 1)
            + 'resource.setrlimit(resource.RLIMIT_CPU,(%d,%d))\n' % (CPU_SECONDS, CPU_SECONDS)
            + 'resource.setrlimit(resource.RLIMIT_NOFILE,(1024,1024))\n'
            'try:\n    os.sched_setaffinity(0,set(sorted(os.sched_getaffinity(0))[:%d]))\nexcept (AttributeError,OSError):\n    pass\n' % MAX_CPUS
            + 'names=%r\ncommand=%r\nbindings={}\n' % (list(names), list(command))
            + 'for name in names:\n'
            '    fd=os.open(name,os.O_RDONLY|getattr(os,"O_NOFOLLOW",0)|getattr(os,"O_NONBLOCK",0))\n'
            '    with os.fdopen(fd,"rb") as stream:\n'
            '        info=os.fstat(stream.fileno())\n'
            '        if not stat.S_ISREG(info.st_mode) or info.st_size>%d: raise ValueError("invalid native input")\n' % MAX_EPUB_BYTES
            + '        data=stream.read(%d)\n' % (MAX_EPUB_BYTES + 1)
            + '    bindings[name]=hashlib.sha256(data).hexdigest()\n'
            + 'Path(%r).write_text(json.dumps(bindings,sort_keys=True))\n' % (stage + '-inputs.json')
            + 'try:\n    os.execve(command[0],command,%r)\nexcept OSError:\n    os._exit(127)\n' % NATIVE_ENVIRONMENT)


def stage_commands(exe):
    """Stage name -> (argument array, bound input names, native output byte limit)."""
    return {'version': ([exe, '--version'], [], OUTPUT_SLACK),
            'check': ([exe, CAPTURE, *CHECK_ARGUMENTS], [CAPTURE], MAX_REPORT_BYTES)}


def read_log(directory, stage, suffix):
    path = Path(directory) / (stage + suffix)
    return bounded(path, 'NATIVE_EXECUTION_FAILED', MAX_LOG_BYTES).decode('utf-8', 'replace') if path.exists() else ''


def overflowed(directory):
    """The check stage's assessment is larger than the report budget, so the capped write was cut short; refuse before reading it as JSON."""
    try:
        size = os.lstat(Path(directory) / ASSESSMENT).st_size
    except OSError:
        return
    if size > MAX_REPORT_BYTES:
        fail('NATIVE_RESOURCE_EXHAUSTED', 'the native assessment reached the %d byte output cap and is truncated (the JVM reports a short write, not a signal)' % MAX_REPORT_BYTES,
             'check', recovery='the publication produces a report larger than the host budget; it is not published')


def classify(directory, stage, command, exit_code):
    """A native stage that did not finish as the checker would: unavailable, resource exhausted or an unknown failure."""
    if stage == 'check':
        overflowed(directory)
    text = (read_log(directory, stage, '.stderr') + read_log(directory, stage, '.stdout')).strip()[-300:]
    code = 'NATIVE_EXECUTION_FAILED'
    if exit_code == 127:
        code = 'NATIVE_UNAVAILABLE'
    elif exit_code in (-9, -24, -25, -6, 137):
        code = 'NATIVE_RESOURCE_EXHAUSTED'
    else:
        for pattern, label in RUNTIME_FAILURES:
            if pattern.search(text):
                code = label
                break
    fail(code, '%s stage %s failed (exit %s): %s' % (Path(command[0]).name, stage, exit_code, text), stage, exitCode=exit_code)


def launch(directory, stage, command, names, limit, accept=(0,)):
    """One native stage through the shared cancellable runner. Returns the exit code, which must be in ``accept``."""
    directory = Path(directory)
    path = directory / (stage + '-launcher.py')
    path.write_text(launcher(stage, names, command, limit))
    try:
        execute([sys.executable, str(path)], directory, stage, remaining_timeout(STAGE_TIMEOUT), {'LANG': 'C.UTF-8'})
        return 0
    except SchemaxisError as error:
        if error.fault.code != 'RUNNER_FAILED':
            raise
        observed = error.fault.observed
        exit_code = observed.get('exitCode')
        if exit_code not in accept or type(exit_code) is not int:
            classify(directory, stage, command, exit_code)
        atomic_json(directory / (stage + '-submission.json'), {**observed, 'nativeCommand': [sys.executable, str(path)]})
        return exit_code


def check_identity(text):
    if not IDENTITY.fullmatch(text):
        fail('UNSUPPORTED_RUNTIME', 'require an observed EPUBCheck 5.4.0 launcher (observed %r); other releases need upstream acceptance' % text[:60], 'version')
    return text.strip()


def check_offline_policy(stderr):
    """The identity stage must show the JVM acknowledging the fixed offline property, with nothing else on stderr."""
    if stderr != OFFLINE_NOTICE:
        fail('UNSUPPORTED_RUNTIME', 'the configured launcher did not apply the fixed offline policy (expected the JVM notice %r on stderr, observed %r); '
             'use a launcher that starts a HotSpot-style Java directly with its environment' % (OFFLINE_NOTICE.strip(), stderr[:120]), 'version')


def check_quiet_stage(directory, code):
    """A quiet check stage may carry exactly the JVM notice on stderr and nothing on stdout; anything else is refused before the report is parsed."""
    if read_log(directory, 'check', '.stderr') != OFFLINE_NOTICE or read_log(directory, 'check', '.stdout'):
        fail(code, 'the native check logged more than the fixed offline notice', 'check')


def run_check(directory, exe, accept):
    """Version probe and the fixed check in ``directory``; returns (identity, exit code). The caller owns the held capture."""
    commands = stage_commands(exe)
    launch(directory, 'version', *commands['version'])
    identity = check_identity(read_log(directory, 'version', '.stdout'))
    check_offline_policy(read_log(directory, 'version', '.stderr'))
    code = launch(directory, 'check', *commands['check'], accept=accept)
    return identity, code


def fresh_check(paths, capture, facts):
    """Check the exact held bytes with the trusted launcher in a private directory; the verdict must be an acceptance."""
    with tempfile.TemporaryDirectory(prefix='schemaxis-epubcheck-') as scratch:
        scratch = Path(scratch)
        (scratch / CAPTURE).write_bytes(capture)
        try:
            identity, code = run_check(scratch, paths['epubcheck'], (0, 1))
        except SchemaxisError as error:
            if error.fault.code != 'NATIVE_EXECUTION_FAILED':
                raise    # unavailable, version, resource, timeout and cancellation faults keep their own codes
            fail('VERIFICATION_FAILED', 'native check failed: ' + error.fault.message, CAPTURE, cause=error.fault.to_dict())
        if code == 0:       # an acceptance needs the exact quiet stage output before its report is parsed; a rejection (exit 1) is refused below and reports its findings
            check_quiet_stage(scratch, 'VERIFICATION_FAILED')
        overflowed(scratch)
        if not (scratch / ASSESSMENT).exists():
            fail('VERIFICATION_FAILED', 'native check wrote no assessment', CAPTURE)
        report = parse_report(bounded(scratch / ASSESSMENT, 'VERIFICATION_FAILED', MAX_REPORT_BYTES), identity, code='VERIFICATION_FAILED')
        counts = severity_counts(report)
        if code != 0 or counts['fatal'] or counts['error'] or counts['warning']:
            fail('VERIFICATION_FAILED', 'a fresh native check no longer accepts the captured publication (exit %s, findings %s)' % (code, counts), CAPTURE, findings=findings(report))
        converted(lambda: bind_items(report, facts, CAPTURE), CAPTURE)
    return report, identity


# ---------------------------------------------------------------- summaries, receipts and evidence
def summarize(facts, capture, report, assessment_bytes, identity):
    publication = report['publication']
    return {'version': SUMMARY_VERSION, 'operation': 'validate',
            'source': {'file': CAPTURE, 'bytes': len(capture), 'sha256': sha(capture), 'members': len(facts['members']), 'directories': facts['directories'],
                       'uncompressedBytes': facts['uncompressedBytes']},
            'checker': {'identity': identity, 'profile': 'default', 'failOnWarnings': True, 'counts': severity_counts(report),
                        'informational': [clean_message(m) for m in report['messages'] if m['severity'] in ('INFO', 'USAGE')][:50]},
            'publication': {key: publication[key] for key in ('title', 'identifier', 'language', 'ePubVersion', 'nSpines', 'isScripted', 'hasFixedFormat',
                                                              'hasEncryption', 'hasSignatures', 'hasAudio', 'hasVideo', 'charsCount')},
            'items': [{'fileName': i['fileName'], 'mediaType': i['media_type'], 'uncompressedBytes': i['uncompressedSize'], 'spineIndex': i['spineIndex']}
                      for i in report['items']],
            'assessment': {'file': ASSESSMENT, 'bytes': len(assessment_bytes), 'sha256': sha(assessment_bytes)},
            'verification': ('A fresh run of the separately configured trusted EPUBCheck on the held captured bytes reproduced every stable assessment field '
                             '(only checkDate and elapsedTime excluded) with zero fatal, error and warning messages. A scoped tool result, not rendering, '
                             'device, accessibility or legal certification.')}


def publications(directory, held=None):
    return [{'file': str(Path(directory) / name), 'kind': 'text', 'sha256': digest(directory, name, held=held)} for name in (ASSESSMENT, SUMMARY)]


def evidence_names():
    names = {'authored.json', 'plan.json', 'captures.json', CAPTURE}
    for stage in ('version', 'check'):
        names.update(stage + suffix for suffix in ('-launcher.py', '-inputs.json', '-submission.json', '.stdout', '.stderr'))
    return names


def unreferenced(directory):
    """Exact top-level membership, including only declared framework sidecars."""
    published = [ASSESSMENT, SUMMARY]
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


def converted(action, location):
    """Retained inputs that no longer satisfy the admission rules are verification failures, never input faults."""
    try:
        return action()
    except SchemaxisError as error:
        if error.fault.code not in SOURCE_FAULTS + ('EPUBCHECK_REPORT_INVALID',):
            raise
        fail('VERIFICATION_FAILED', 'retained %s is invalid (%s): %s' % (location, error.fault.code, error.fault.message), location, cause=error.fault.to_dict())


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
        fail('OUTPUT_EXISTS', 'select a fresh EPUBCheck publication directory', str(directory))
    try:
        directory.mkdir(parents=True)
    except FileExistsError:
        fail('OUTPUT_EXISTS', 'select a fresh EPUBCheck publication directory', str(directory))
    atomic_json(directory / 'authored.json', document)
    atomic_json(directory / 'plan.json', prepared)
    atomic_json(directory / 'result.json', {'status': 'incomplete', 'verified': False})
    try:
        with execution_deadline(timeout):
            capture = bounded(prepared['source'], 'INVALID_EPUB_SOURCE', MAX_EPUB_BYTES, '$.source')
            facts = preflight(capture, '$.source')
            (directory / CAPTURE).write_bytes(capture)
            atomic_json(directory / 'captures.json', {'source': prepared['source'], 'bytes': len(capture), 'sha256': sha(capture)})
            identity, code = run_check(directory, paths['epubcheck'], (0, 1))
            target = directory / ASSESSMENT
            overflowed(directory)
            if not target.exists():
                classify(directory, 'check', stage_commands(paths['epubcheck'])['check'][0], code)
            assessment = bounded(target, 'EPUBCHECK_REPORT_INVALID', MAX_REPORT_BYTES)
            report = parse_report(assessment, identity)
            counts = severity_counts(report)
            rejected = bool(counts['fatal'] or counts['error'] or counts['warning'])
            if rejected != (code == 1):
                fail('EPUBCHECK_REPORT_INVALID', 'exit status %d disagrees with the reported counts %s' % (code, counts), ASSESSMENT)
            if rejected:
                os.replace(target, directory / REJECTED)
                fail('EPUBCHECK_REJECTED', 'EPUBCheck reported %d fatal, %d error and %d warning messages; see rejected-assessment.json and fix the publication' %
                     (counts['fatal'], counts['error'], counts['warning']), '$.source', findings=findings(report), assessment=REJECTED,
                     recovery='fix the listed EPUBCheck findings (message IDs are documented by the EPUBCheck project) and run again; nothing was published')
            bind_items(report, facts, ASSESSMENT)
            if bounded(directory / CAPTURE, limit=MAX_EPUB_BYTES) != capture:
                fail('VERIFICATION_FAILED', 'captured EPUB changed during the native check', CAPTURE)
            atomic_json(directory / SUMMARY, summarize(facts, capture, report, assessment, identity))
            atomic_json(directory / 'verification.json', {
                'artifacts': publications(directory), 'evidence': {n: digest(directory, n) for n in sorted(evidence_names())},
                'runtime': {'epubcheck': identity}, 'executables': paths})
            verified = verify_semantic(directory, paths, require_result=False)
            remaining_timeout(STAGE_TIMEOUT)
            result = {'status': 'succeeded', **verified}
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

    Only ``status`` (checked separately) and the text of ``runtime.freshCheck`` are excluded, because that identity legitimately
    varies with the verifying launcher; it must still be present and an EPUBCheck 5.4.0 identity string.
    """
    claims = {key: value for key, value in result.items() if key != 'status'}
    runtime_record = claims.get('runtime')
    if isinstance(runtime_record, dict):
        fresh = runtime_record.get('freshCheck')
        claims['runtime'] = {**{key: value for key, value in runtime_record.items() if key != 'freshCheck'},
                             'freshCheck': isinstance(fresh, str) and IDENTITY.fullmatch(fresh) is not None}
    return claims


def verify_semantic(directory, paths, require_result=True):
    """Judge the published assessment from the authored request, held capture and a fresh native check.

    The decision is: the captured EPUB bytes (read once and held) pass the host container preflight, and the trusted launcher, run now
    in a separate process on a private copy of exactly those bytes, accepts them (exit 0, zero fatal/error/warning) with a closed
    typed report whose stable fields (everything except checkDate and elapsedTime) equal the retained published assessment, whose items
    equal the container files and whose recomputed summary equals the published one. Retained launchers, input bindings, submissions
    and the receipt are hash-bound consistency diagnostics and are never re-executed; receipt executables are inert provenance. The
    captured file is a writable, unauthenticated copy. The judgement covers the bytes read during this call; the captured bytes are
    re-read at the end to detect a concurrent change, but a writer that changes other files afterwards is not guarded against.
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
                fail('INCOMPLETE_EXECUTION', 'EPUBCheck publication did not complete or was rejected by the checker')
            extra = unreferenced(directory)
            if extra:
                fail('VERIFICATION_FAILED', 'unreferenced files in the publication directory: ' + ', '.join(extra[:8]))
            held = {}
            capture = held[CAPTURE] = bounded(directory / CAPTURE, limit=MAX_EPUB_BYTES)
            if not same_json(read_json(directory, 'captures.json'), {'source': prepared['source'], 'bytes': len(capture), 'sha256': sha(capture)}):
                fail('VERIFICATION_FAILED', 'source capture record differs from the captured bytes')
            facts = converted(lambda: preflight(capture, CAPTURE), CAPTURE)
            fresh, fresh_identity = fresh_check(paths, capture, facts)
            saved = held[ASSESSMENT] = bounded(directory / ASSESSMENT, limit=MAX_REPORT_BYTES)
            version_text = bounded(directory / 'version.stdout', limit=MAX_LOG_BYTES).decode('utf-8', 'replace')
            try:
                observed = check_identity(version_text)
            except SchemaxisError:
                fail('VERIFICATION_FAILED', 'retained version output is not an EPUBCheck 5.4.0 identity', 'version')
            retained = converted(lambda: parse_report(saved, observed, code='VERIFICATION_FAILED'), ASSESSMENT)
            if not same_json(stable(retained), stable(fresh)):
                fail('VERIFICATION_FAILED', 'retained assessment differs from the fresh native assessment of the captured bytes', ASSESSMENT)
            converted(lambda: bind_items(retained, facts, ASSESSMENT), ASSESSMENT)
            summary = summarize(facts, capture, retained, saved, observed)
            held[SUMMARY] = bounded(directory / SUMMARY, limit=MAX_LOG_BYTES)
            if not same_json(strict_json(held[SUMMARY], SUMMARY), summary):
                fail('VERIFICATION_FAILED', 'retained summary differs from the recomputed observation')
            receipt = read_json(directory, 'verification.json')
            if not isinstance(receipt, dict) or not same_json(receipt.get('artifacts'), publications(directory, held)):
                fail('VERIFICATION_FAILED', 'publication membership or digests differ from the receipt')
            evidence = receipt.get('evidence')
            if not isinstance(evidence, dict) or set(evidence) != evidence_names():
                fail('VERIFICATION_FAILED', 'retained evidence membership differs')
            for name in sorted(evidence_names()):
                if digest(directory, name, held=held) != evidence[name]:
                    fail('VERIFICATION_FAILED', 'retained evidence differs', name)
            recorded = receipt.get('executables')
            if not isinstance(recorded, dict) or set(recorded) != {'epubcheck'} or not isinstance(recorded['epubcheck'], str) or not os.path.isabs(recorded['epubcheck']):
                fail('VERIFICATION_FAILED', 'receipt executable identity must be absolute provenance')
            runtimes = receipt.get('runtime')
            if not isinstance(runtimes, dict) or set(runtimes) != {'epubcheck'} or runtimes['epubcheck'] != observed:
                fail('VERIFICATION_FAILED', 'recorded runtime identity differs from the retained version output', 'version')
            for stage, (command, names, limit) in stage_commands(recorded['epubcheck']).items():
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
                if bounded(directory / (stage + '.stderr'), limit=MAX_LOG_BYTES) != OFFLINE_NOTICE.encode() or (
                        stage != 'version' and bounded(directory / (stage + '.stdout'), limit=MAX_LOG_BYTES)):
                    fail('VERIFICATION_FAILED', 'a native stage logged more than the fixed offline notice', stage)
            if bounded(directory / CAPTURE, limit=MAX_EPUB_BYTES) != capture:
                fail('VERIFICATION_FAILED', 'captured EPUB changed while it was being verified', CAPTURE)
            remaining_timeout(VERIFY_TIMEOUT)
            verified = {'verified': True, 'operation': 'validate', 'artifacts': 2,
                        'source': {'bytes': len(capture), 'sha256': sha(capture), 'members': len(facts['members']), 'uncompressedBytes': facts['uncompressedBytes']},
                        'checker': {'counts': severity_counts(retained), 'items': len(retained['items'])},
                        'runtime': {'epubcheck': runtimes['epubcheck'], 'freshCheck': fresh_identity}}
            if require_result and not same_json(result_claims(recorded_result), result_claims(verified)):
                fail('VERIFICATION_FAILED', 'retained result claims differ from the verified observation')
            return verified
    except (OSError, ValueError, KeyError, TypeError, IndexError, AttributeError, UnicodeError, RecursionError, StopIteration) as error:
        fail('VERIFICATION_FAILED', 'invalid retained EPUBCheck evidence: %s %s' % (type(error).__name__, str(error)[:80]))


def reusableInputs(document):
    prepared = plan(document)
    source = prepared['source']
    data = bounded(source, 'INVALID_EPUB_SOURCE', MAX_EPUB_BYTES, '$.source')
    preflight(data, '$.source')
    return {source: sha(data)}


def verify(directory, require_result=True, *, executable=None):
    return verify_semantic(directory, runtime(executable), require_result)


from schemaxis.adaptor_runtime import bind as _bind_runtime
_bind_runtime(globals())
