"""Strict host-side closure checks for captured ParaView reader inputs.

These checks never open paths outside the captured ``data`` directory and never
run native code. They are deliberately narrower than the native readers: input
outside the supported subset is refused rather than assumed harmless.
"""
from pathlib import Path
import re
import xml.etree.ElementTree as ET
import zlib

from schemaxis.errors import fail


# VTK XML documents: suffix (case-insensitive) -> declared VTKFile type.
LEAVES = {'.vtp': 'PolyData', '.vtu': 'UnstructuredGrid', '.vti': 'ImageData',
          '.vts': 'StructuredGrid', '.vtr': 'RectilinearGrid'}
CONTAINERS = {'.vtm': 'vtkMultiBlockDataSet', '.pvtp': 'PPolyData', '.pvtu': 'PUnstructuredGrid',
              '.pvti': 'PImageData', '.pvts': 'PStructuredGrid', '.pvtr': 'PRectilinearGrid'}
# Reader -> the root document it opens. Parallel pieces must be the matching leaf type.
ROOTS = {'readMultiBlock': 'vtkMultiBlockDataSet', 'readParallelPolyData': 'PPolyData',
         'readParallelUnstructuredGrid': 'PUnstructuredGrid'}
HEADER_BYTES = 65536
# Container metadata has separate work limits from the captured payload size.
# Leaf payloads are still header-checked only (including raw appended arrays).
XML_CHUNK = 65536
XML_MAX_CONTAINER_BYTES = 16 << 20
XML_MAX_TOTAL_BYTES = 64 << 20
XML_MAX_REFERENCES = 65536
XML_MAX_DEPTH = 128
_PROLOGUE = re.compile(rb'\A(?:\xef\xbb\xbf)?\s*(?:<\?xml[^<>]*\?>\s*)?(?:<!--(?:(?!-->).)*-->\s*)*'
                       rb'<VTKFile(\s[^<>]*)?>', re.S)
_TYPE = re.compile(rb'''\stype\s*=\s*(?:"([^"]*)"|'([^']*)')''')


def _refuse(message, path, **details):
    fail('UNSUPPORTED_RESOURCE', message, str(path), **details)


def document_type(path):
    """Return the VTKFile type from a bounded prefix; payloads are never parsed."""
    with open(path, 'rb') as stream:
        prefix = stream.read(HEADER_BYTES)
    match = _PROLOGUE.match(prefix)
    types = _TYPE.findall(match.group(1) or b'') if match else []
    if len(types) != 1:
        _refuse('member is not a recognised VTK XML document within the bounded header', path)
    try:
        return (types[0][0] or types[0][1]).decode('ascii')
    except UnicodeDecodeError:
        _refuse('VTK XML document type is not ASCII', path)


def _expected(path):
    suffix = Path(path).suffix.lower()
    expected = LEAVES.get(suffix) or CONTAINERS.get(suffix)
    if expected is None:
        _refuse('captured XML member name is not a supported VTK XML format', path, suffix=Path(path).suffix)
    return expected


def xml_closure(reader, path, data, files):
    """Return captured members opened by ``reader`` from ``path``; refuse anything unproven.

    Every document's type is read from its header and must match its suffix, so
    a container renamed as a leaf cannot hide references. Containers are streamed
    and traversed; leaves are only header-checked. Every reference must be a
    relative path naming an exact captured member. Metadata bytes, reference
    occurrences and element depth are bounded independently of payload sizes.
    """
    data, captured = Path(data).resolve(), set(files)
    root = Path(path).resolve()
    if _expected(root) != ROOTS[reader]:
        _refuse(reader + ' opens a ' + ROOTS[reader] + ' document; the selected member has another format', root)
    pending, scheduled, types = [(root, None)], {(root, None)}, {}
    total_bytes, references = 0, 0
    while pending:
        current, required = pending.pop()
        visited = current in types
        if not visited:
            if not current.is_relative_to(data):
                _refuse('reference escapes the captured snapshot', current)
            relative = current.relative_to(data).as_posix()
            if relative not in captured or not current.is_file():
                _refuse('reference is not a captured member', current, member=relative)
            declared = document_type(current)
            if declared != _expected(current):
                _refuse('VTK XML document type differs from its name or referencing container', current,
                        declared=declared, expected=_expected(current))
            types[current] = declared
        declared = types[current]
        # A cached document may be reached through a different parallel reader.
        # Reusing its header must not skip that edge's required piece type.
        if required is not None and declared != required:
            _refuse('VTK XML document type differs from its name or referencing container', current,
                    declared=declared, expected=required)
        if visited:
            continue
        if declared not in CONTAINERS.values():
            continue
        piece = declared[1:] if declared != 'vtkMultiBlockDataSet' else None
        try:
            parser, parents, container_bytes = ET.XMLPullParser(events=('start', 'end')), [], 0
            with open(current, 'rb') as stream:
                while True:
                    # Read at most one byte beyond a remaining budget so file
                    # growth or misleading metadata cannot bypass the bounds.
                    remaining = min(XML_MAX_CONTAINER_BYTES - container_bytes,
                                    XML_MAX_TOTAL_BYTES - total_bytes)
                    chunk = stream.read(min(XML_CHUNK, remaining + 1))
                    if not chunk:
                        break
                    container_bytes += len(chunk)
                    total_bytes += len(chunk)
                    if container_bytes > XML_MAX_CONTAINER_BYTES or total_bytes > XML_MAX_TOTAL_BYTES:
                        _refuse('VTK XML container metadata exceeds the scan byte limit', current)
                    parser.feed(chunk)
                    for event, element in parser.read_events():
                        if event == 'start':
                            if len(parents) >= XML_MAX_DEPTH:
                                _refuse('VTK XML container exceeds the element depth limit', current)
                            parents.append(element)
                            continue
                        for key in ('Source', 'file'):
                            if key not in element.attrib:
                                continue
                            references += 1
                            if references > XML_MAX_REFERENCES:
                                _refuse('VTK XML closure exceeds the reference count limit', current)
                            reference = Path(element.attrib[key])
                            if not element.attrib[key] or reference.is_absolute():
                                _refuse('container has an empty or absolute reference', current,
                                        reference=element.attrib[key])
                            entry = ((current.parent/reference).resolve(), piece)
                            if entry not in scheduled:
                                scheduled.add(entry)
                                pending.append(entry)
                        parents.pop()
                        if parents:
                            parents[-1].remove(element)
                        element.clear()
                parser.close()
        except ET.ParseError as error:
            _refuse('VTK XML container is not well-formed', current, reason=str(error))
    return sorted(path.relative_to(data).as_posix() for path in types)


# OpenFOAM: a fail-closed lexical subset. Any active '#' is refused, so no
# include or other preprocessing directive is ever expanded or opened.
#
# The basis is the vtkOpenFOAMReader shipped with ParaView 5.13.3 (VTK source,
# not a guarantee for other versions). Its case root is the selected file's
# directory, or that directory's parent when the file name begins with
# "controlDict"; such selections are refused so the root never leaves the
# scanned subtree. From the root it opens system/, constant/ (including
# constant/<region>/polyMesh), processor*/ and time directories whose names start
# with a digit, '+' or '-'. The scope below is a superset: every file beneath
# system/, constant/ and processor* (any letter case) and beneath any top-level
# directory not starting with a letter (plus inf*/nan*) is scanned whatever its
# name or suffix. Other top-level files and letter-named directories (logs,
# scripts, postProcessing) are left unscanned because that reader does not open them.
FOAM_CHUNK = 1 << 20
FOAM_MAX_FILE_BYTES = 1 << 29      # decompressed bytes scanned per file (512 MiB)
FOAM_MAX_TOTAL_BYTES = 1 << 31     # decompressed bytes scanned per case (2 GiB)
# The native tokeniser stores at most 1024 bytes of a quoted string and resumes
# ordinary tokenising after that, so a longer string could hide an active '#'.
# Refuse strings well before that cap, leaving room for delimiters.
FOAM_MAX_STRING_BYTES = 1000
FOAM_SCOPE = ('selected member (names beginning with "controlDict" are refused)',
              'every file under system/, constant/ and processor*/ (any letter case)',
              'every file under top-level directories whose names do not start with a letter, '
              'or start with inf or nan (possible times)',
              'basis: ParaView 5.13.3 vtkOpenFOAMReader case layout; other top-level entries are not scanned')
FOAM_SUBSET = ('ASCII dictionaries and fields, optionally gzip-compressed (magic-detected, any name)',
               'no active "#" token: every directive (#include, #sinclude, #includeIfPresent, #includeEtc, '
               '#includeFunc, #calc, #codeStream, #{...#}) is refused',
               '"//" and "/*...*/" comments and single-line strings without backslashes at token starts, '
               'with at most %d bytes between the quotes' % FOAM_MAX_STRING_BYTES,
               'binary format (the word "binary"), control bytes, nested "/*", ambiguous '
               'quote/comment starts, multi-line, escaped or overlong strings and bare carriage returns '
               'are refused',
               '$variable references are left to the native reader; they do not open files')
_NORMAL = re.compile(rb'[#"/\r\x00-\x08\x0e-\x1f\x7f]')
_STRING = re.compile(rb'["\\\n\r]')
_BLOCK = re.compile(rb'\*/|/\*')
_BINARY = re.compile(rb'(?<![A-Za-z0-9_])binary(?![A-Za-z0-9_])')
_HEAD = re.compile(rb'(?:^|[\s;{}])[()]*\Z')


class _FoamScanner:
    def __init__(self, path):
        self.path, self.state, self.buffer, self.head, self.offset = path, 'normal', b'', 0, 0
        # Buffer position of the open string's first content byte; shifted with the buffer.
        self.string = 0

    def refuse(self, message):
        _refuse('OpenFOAM case input is outside the supported lexical subset: ' + message, self.path)

    def at_head(self, text, index):
        # VTK starts strings and comments only at token heads. Look back over
        # parentheses to whitespace, ';', '{', '}' or the end of a comment/string.
        start = index
        while start > 0 and text[start-1:start] in (b'(', b')'):
            start -= 1
        return start == self.head or bool(_HEAD.search(text[max(start-1, 0):start])) and start > 0

    def feed(self, chunk, final=False):
        text = self.buffer + chunk
        keep = 0 if final else min(len(text), 512)
        if _BINARY.search(text):
            self.refuse('binary format is not supported')
        index, limit = self.offset, len(text) - keep
        while index < limit:
            if self.state == 'normal':
                match = _NORMAL.search(text, index, limit)
                if match is None:
                    index = limit
                    break
                index, char = match.start(), match.group()
                if char == b'#':
                    self.refuse('active "#" directive')
                if char == b'\r':
                    if text[index+1:index+2] != b'\n' and (final or index+1 < len(text)):
                        self.refuse('bare carriage return')
                    index += 1
                    continue
                if char not in (b'"', b'/'):
                    self.refuse('binary or control byte')
                following = text[index+1:index+2]
                if char == b'/' and following not in (b'/', b'*'):
                    index += 1
                    continue
                if not self.at_head(text, index):
                    self.refuse('quote or comment adjoins a word')
                self.state = 'string' if char == b'"' else 'line' if following == b'/' else 'block'
                index += 1 if char == b'"' else 2
                self.string = index
            elif self.state == 'string':
                match = _STRING.search(text, index, limit)
                if (match.start() if match else limit) - self.string > FOAM_MAX_STRING_BYTES:
                    self.refuse('quoted string longer than %d bytes' % FOAM_MAX_STRING_BYTES)
                if match is None:
                    index = limit
                    break
                if match.group() != b'"':
                    self.refuse('multi-line or escaped string')
                self.state, index = 'normal', match.end()
                self.head = index
            elif self.state == 'line':
                end = text.find(b'\n', index, limit)
                if end < 0:
                    index = limit
                    break
                if text[end-1:end] == b'\\' or text[end-2:end] == b'\\\r':
                    self.refuse('line comment continued with a backslash')
                self.state, index = 'normal', end + 1
                self.head = index
            else:
                match = _BLOCK.search(text, index, limit + (0 if final else 1))
                if match is None:
                    index = limit
                    break
                if match.group() == b'/*':
                    self.refuse('nested block comment')
                self.state, index = 'normal', match.end()
                self.head = index
        # Control bytes are binary in every state.
        if re.search(rb'[\x00-\x08\x0e-\x1f\x7f]', text[:index]):
            self.refuse('binary or control byte')
        # Keep enough history to judge token heads and two-byte openers.
        history = max(0, index - 256)
        self.buffer, self.head, self.offset = text[history:], self.head - history, index - history
        self.string -= history
        if final and self.state not in ('normal', 'line'):
            self.refuse('unterminated string or block comment')


def _foam_stream(path):
    """Yield decompressed chunks with explicit bounds; truncated gzip fails."""
    with open(path, 'rb') as stream:
        first = stream.read(FOAM_CHUNK)
        if first[:2] != b'\x1f\x8b':
            while first:
                yield first
                first = stream.read(FOAM_CHUNK)
            return
        inflater, pending = zlib.decompressobj(16 + zlib.MAX_WBITS), first
        try:
            while True:
                if not pending and not inflater.eof:
                    pending = stream.read(FOAM_CHUNK)
                    if not pending:
                        # Drain buffered output only; a stream without its end is truncated.
                        output = inflater.decompress(b'', FOAM_CHUNK)
                        if not output:
                            _refuse('truncated gzip OpenFOAM input', path)
                        yield output
                        continue
                output = inflater.decompress(pending, FOAM_CHUNK)
                pending = inflater.unconsumed_tail
                if output:
                    yield output
                if inflater.eof:
                    rest = inflater.unused_data + pending + stream.read(2)
                    if not rest:
                        return
                    if rest[:2] != b'\x1f\x8b':
                        _refuse('trailing data after gzip OpenFOAM input', path)
                    inflater, pending = zlib.decompressobj(16 + zlib.MAX_WBITS), rest
        except zlib.error as error:
            _refuse('invalid gzip OpenFOAM input', path, reason=str(error))


def _foam_scope(relative, case):
    """Whether ``relative`` (POSIX, data-relative) lies in the scanned superset of
    what the ParaView 5.13.3 OpenFOAM reader may open below ``case``; see FOAM_SCOPE."""
    parts = Path(relative).parts
    prefix = Path(case).parts
    if parts[:len(prefix)] != prefix or len(parts) <= len(prefix) + 1:
        return False
    lower = parts[len(prefix)].lower()
    return (lower in ('system', 'constant') or lower.startswith(('processor', 'inf', 'nan'))
            or not lower[:1].isalpha())


def foam_closure(member, data, files):
    """Scan every captured file the OpenFOAM reader may open; return scan evidence."""
    data = Path(data)
    # The native reader takes the parent directory as the case root for any
    # selected name beginning with "controlDict" (controlDict.gz, controlDict.x),
    # which may lie outside the scanned subtree or the snapshot. Compare
    # case-insensitively so case-folding file systems are also covered.
    if Path(member).name.lower().startswith('controldict'):
        _refuse('select a case marker file such as case.foam, not a name beginning with controlDict', member)
    case = Path(member).parent.as_posix()
    case = '' if case == '.' else case
    scanned, total = [], 0
    for relative in sorted(files):
        if relative != member and not _foam_scope(relative, case):
            continue
        scanner, size = _FoamScanner(data/relative), 0
        for chunk in _foam_stream(data/relative):
            size += len(chunk)
            total += len(chunk)
            if size > FOAM_MAX_FILE_BYTES or total > FOAM_MAX_TOTAL_BYTES:
                _refuse('OpenFOAM input exceeds the decompressed scan limit', data/relative,
                        fileLimit=FOAM_MAX_FILE_BYTES, totalLimit=FOAM_MAX_TOTAL_BYTES)
            scanner.feed(chunk)
        scanner.feed(b'', final=True)
        scanned.append(relative)
    return {'scannedMembers': len(scanned), 'scannedBytes': total,
            'unscannedMembers': len(files) - len(scanned), 'scanScope': list(FOAM_SCOPE),
            'supportedSubset': list(FOAM_SUBSET),
            'limits': {'fileBytes': FOAM_MAX_FILE_BYTES, 'totalBytes': FOAM_MAX_TOTAL_BYTES,
                       'quotedStringBytes': FOAM_MAX_STRING_BYTES}}
