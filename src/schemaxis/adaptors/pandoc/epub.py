"""Independent EPUB3 package and content checks for the report route, and a strict reader for Pandoc's own EPUB readback.

Pandoc 3.12.1 writes the package; nothing here trusts it. The ZIP container, the closed member set, the OPF
manifest/spine/navigation cross-references and every XHTML chapter are read with the host standard library and
compared with the authored report model. The fresh native EPUB reader JSON is a second, independent comparison.
This proves a bounded package and content profile only: it is not EPUBCheck, reading-system rendering,
device behaviour or accessibility conformance.
"""
import hashlib
import io
import re
import stat
import struct
import xml.etree.ElementTree as ET
import zipfile
import zlib

from schemaxis.errors import fail

from .inspection import declared, meta_authors, require

LANGUAGE = re.compile(r'[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8}){0,3}', re.ASCII)
MAX_LANGUAGE = 35
# Bounds of the EPUB publication: the package is refused, never truncated, beyond them.
MAX_ENTRIES = 96
MAX_PACKAGE_BYTES = 32 * 1024 * 1024
MAX_PART_BYTES = 8 * 1024 * 1024
MAX_MEDIA_BYTES = 4 * 1024 * 1024
MAX_DEPTH = 3

# Reviewed native Pandoc 3.12.1 EPUB3 writer parts whose bytes never depend on the report. A changed part needs
# review and fresh native qualification; an editable run receipt cannot approve new content, scripts or styles.
FIXED_PARTS = {
    'META-INF/container.xml': '7c06491ce25e3cc80ccec0eed382c4c5570265f886415e4ce0cbe5866a57c461',
    'META-INF/com.apple.ibooks.display-options.xml': '364a17d7a4967325d2956f09c0626d564c1884c9dfa02116dc115d6a49538f56',
    'EPUB/styles/stylesheet1.css': '932ab19ee3371838c3dd65eb770a6515e2730fc1c4bdd5a533984f2e355c8b24'}
MIMETYPE = b'application/epub+zip'
XML_DECLARATION = b'<?xml version="1.0" encoding="UTF-8"?>\n'
HTML5_DOCTYPE = b'<!DOCTYPE html>\n'
SAFE_NAME = re.compile(r'[A-Za-z0-9_.\-]+(?:/[A-Za-z0-9_.\-]+)*')
UUID = re.compile(r'urn:uuid:[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}')
MEDIA_NAME = re.compile(r'EPUB/media/file([0-9]+)\.png')
IMAGE_SOURCE = re.compile(r'\.\./media/file([0-9]+)\.png')
IMAGE_WIDTH = re.compile(r'width:([0-9]+(?:\.[0-9]+)?)mm')
IBOOKS = 'ibooks: http://vocabulary.itunes.apple.com/rdf/ibooks/vocabulary-extensions-1.0/'
FIXED_DATE = '1970-01-01T00:00:00Z'

XHTML = '{http://www.w3.org/1999/xhtml}'
OPS = '{http://www.idpf.org/2007/ops}type'
XMLLANG = '{http://www.w3.org/XML/1998/namespace}lang'
OPF = '{http://www.idpf.org/2007/opf}'
DC = '{http://purl.org/dc/elements/1.1/}'
NCX = '{http://www.daisy.org/z3986/2005/ncx/}'
CONTAINER = '{urn:oasis:names:tc:opendocument:xmlns:container}'
ACCESSIBILITY = [('schema:accessMode', 'textual'), ('schema:accessModeSufficient', 'textual'), ('schema:accessibilityFeature', 'alternativeText'),
                 ('schema:accessibilityFeature', 'readingOrder'), ('schema:accessibilityFeature', 'structuralNavigation'),
                 ('schema:accessibilityFeature', 'tableOfContents'), ('schema:accessibilityHazard', 'none')]


def valid_language(value):
    """True only for a plain ASCII language tag: 2-3 letter primary subtag and up to three simple hyphen subtags."""
    return type(value) is str and len(value) <= MAX_LANGUAGE and LANGUAGE.fullmatch(value) is not None


def blank(text): return text is None or not text.strip()


def xml_part(data, name, doctype=False):
    """Parse one XML part after the exact writer prologue; comments, processing instructions, DTDs and CDATA are refused."""
    require(data.startswith(XML_DECLARATION), 'EPUB part lacks the writer XML declaration: ' + name)
    rest = data[len(XML_DECLARATION):]
    if doctype:
        require(rest.startswith(HTML5_DOCTYPE), 'EPUB XHTML document type differs from the HTML5 doctype: ' + name)
        rest = rest[len(HTML5_DOCTYPE):]
    require(b'<!' not in rest and b'<?' not in rest, 'EPUB part holds a comment, processing instruction, CDATA section or extra document type: ' + name)
    return ET.fromstring(rest)


def leaf(node, tag, attrib=None, text=None):
    """An element with no children and the exact attributes; returns its literal text."""
    require(node.tag == tag and dict(node.attrib) == (attrib or {}) and len(node) == 0 and blank(node.tail), 'unexpected EPUB element: ' + node.tag.rsplit('}', 1)[-1])
    if text is not None: require((node.text or '') == text, 'EPUB element text differs: ' + node.tag.rsplit('}', 1)[-1])
    return node.text or ''


def container(node, tag, tags, attrib=None):
    """An element holding only whitespace and the listed child tags, in exactly that order."""
    require(node.tag == tag and dict(node.attrib) == (attrib or {}) and blank(node.text) and blank(node.tail)
            and [c.tag for c in node] == tags, 'unexpected EPUB structure: ' + node.tag.rsplit('}', 1)[-1])
    return list(node)


LOCAL = struct.Struct('<4sHHHHHIIIHH')
CENTRAL = struct.Struct('<4sHHHHHHIIIHHHHHII')
END = struct.Struct('<4sHHHHIIH')
DESCRIPTOR_SIGNATURE = b'PK\x07\x08'


def descriptor_length(data, offset, crc, packed, size):
    """Length of a lawful data descriptor (optional signature, CRC-32, sizes) that repeats the central values, else a refusal."""
    values = struct.pack('<III', crc, packed, size)
    if data[offset:offset + 16] == DESCRIPTOR_SIGNATURE + values: return 16
    require(data[offset:offset + 12] == values, 'EPUB data descriptor differs from the central directory')
    return 12


def inflate(raw, size, name):
    """Exactly `size` bytes from a complete raw deflate stream with nothing left over; never more than one byte past the declared size."""
    stream = zlib.decompressobj(-15); body = stream.decompress(raw, size + 1)
    require(stream.eof and not stream.unused_data and not stream.unconsumed_tail and len(body) == size, 'EPUB deflate stream differs from its header: ' + name)
    return body


def frame(data):
    """The physical ZIP framing of a Pandoc-style package, read from the raw bytes and cross-checked against the central directory.

    Conservative fixed profile: no prefix, no gap or hidden bytes between members, local headers in central order with no extra
    fields, no ZIP64, no archive or entry comment, no disks, and the end record last. Every local header repeats the central
    version, flags, method, time, name, CRC-32 and sizes (a lawful trailing data descriptor may carry the last three).
    Returns [(central fields, name, packed bytes)] in physical order.
    """
    require(len(data) <= MAX_PACKAGE_BYTES and len(data) >= END.size and data[:4] == b'PK\x03\x04', 'EPUB archive does not start with a local file header')
    signature, disk, directory_disk, here, total, size, offset, comment = END.unpack_from(data, len(data) - END.size)
    require(signature == b'PK\x05\x06' and (disk, directory_disk, comment) == (0, 0, 0) and here == total,
            'EPUB archive must end with exactly one end record without comment, disk or ZIP64 fields')
    require(0 < total <= MAX_ENTRIES, 'EPUB archive entry limit or comment')
    require(offset + size == len(data) - END.size, 'EPUB central directory is not directly before the end record')
    entries = []; position = offset
    for _ in range(total):
        require(position + CENTRAL.size <= offset + size, 'EPUB central directory is truncated')
        (signature, made, needed, flags, method, clock, day, crc, packed, unpacked, name_length, extra_length, comment_length, disk_start,
         internal, external, header) = CENTRAL.unpack_from(data, position)
        require(signature == b'PK\x01\x02', 'EPUB central header signature differs')
        start = position + CENTRAL.size; position = start + name_length
        require(position <= offset + size, 'EPUB central directory is truncated')
        try: name = data[start:position].decode('ascii')
        except UnicodeDecodeError: fail('VERIFICATION_FAILED', 'unsafe EPUB archive member name')
        require((extra_length, comment_length, disk_start, internal) == (0, 0, 0, 0), 'EPUB central header uses an extra field, comment, disk or text attribute: ' + name)
        entries.append({'name': name, 'made': made, 'needed': needed, 'flags': flags, 'method': method, 'clock': clock, 'day': day, 'crc': crc,
                        'packed': packed, 'size': unpacked, 'external': external, 'header': header})
    require(position == offset + size, 'EPUB central directory holds bytes beyond its entries')
    names = [e['name'] for e in entries]
    require(len(set(names)) == len(names) and len({n.lower() for n in names}) == len(names), 'duplicate EPUB archive member')
    require(sum(e['size'] for e in entries) <= MAX_PACKAGE_BYTES, 'EPUB archive exceeds the uncompressed byte limit')
    expected = 0; framed = []
    for entry in entries:
        name = entry['name']
        require(SAFE_NAME.fullmatch(name) is not None and '..' not in name.split('/') and '.' not in name.split('/'), 'unsafe EPUB archive member name')
        require(not entry['flags'] & ~0x0808 and entry['method'] in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED), 'EPUB encrypted or unsupported compression: ' + name)
        mode = entry['external'] >> 16
        require(not entry['external'] & 0x10 and stat.S_IFMT(mode) in (0, stat.S_IFREG), 'EPUB archive member is not a regular file: ' + name)
        require(entry['header'] == expected, 'EPUB member is not where the previous member ends (prefix, gap, hidden bytes or reordered central directory): ' + name)
        limit = MAX_MEDIA_BYTES if name.startswith('EPUB/media/') else MAX_PART_BYTES
        require(entry['size'] <= limit, 'EPUB archive member exceeds its byte limit: ' + name)
        require(entry['method'] == zipfile.ZIP_DEFLATED or entry['packed'] == entry['size'], 'EPUB stored member size differs from its header: ' + name)
        require(expected + LOCAL.size + len(name) <= offset, 'EPUB local header runs into the central directory: ' + name)
        (signature, needed, flags, method, clock, day, crc, packed, unpacked, name_length, extra_length) = LOCAL.unpack_from(data, expected)
        descriptor = bool(entry['flags'] & 8)
        sums = (crc, packed, unpacked) in ((entry['crc'], entry['packed'], entry['size']), (0, 0, 0) if descriptor else None)
        require(signature == b'PK\x03\x04' and (needed, flags, method, clock, day) == (entry['needed'], entry['flags'], entry['method'], entry['clock'], entry['day'])
                and (name_length, extra_length) == (len(name), 0) and sums and data[expected + LOCAL.size:expected + LOCAL.size + name_length] == name.encode('ascii'),
                'EPUB local header differs from its central entry (flags, method, name, CRC-32, sizes or extra field): ' + name)
        begin = expected + LOCAL.size + name_length; finish = begin + entry['packed']
        require(finish <= offset, 'EPUB member data runs into the central directory: ' + name)
        expected = finish + (descriptor_length(data, finish, entry['crc'], entry['packed'], entry['size']) if descriptor else 0)
        framed.append((entry, name, data[begin:finish], limit))
    require(expected == offset, 'EPUB members do not end exactly at the central directory')
    return framed


def members(data):
    """Safe bounded read of every ZIP member: exact physical framing, regular, unique, ASCII-safe names, no encryption, exact sizes and CRCs."""
    framed = frame(data)
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        # The standard reader must agree with the framing read above; any disagreement between two readers is a refusal.
        require(archive.comment == b'' and [(i.filename, i.header_offset, i.CRC, i.compress_size, i.file_size) for i in archive.infolist()]
                == [(e['name'], e['header'], e['crc'], e['packed'], e['size']) for e, _, _, _ in framed], 'EPUB archive readers disagree about the central directory')
    found = {}
    for entry, name, raw, limit in framed:
        body = raw if entry['method'] == zipfile.ZIP_STORED else inflate(raw, entry['size'], name)
        require(len(body) == entry['size'] and zlib.crc32(body) == entry['crc'], 'EPUB archive member size or CRC-32 differs from its header: ' + name)
        found[name] = body
    first = framed[0][0]
    require(framed[0][1] == 'mimetype' and first['method'] == zipfile.ZIP_STORED and first['header'] == 0 and found['mimetype'] == MIMETYPE,
            'EPUB mimetype must be the first member at offset 0, stored, without extra field, and exactly ' + MIMETYPE.decode())
    return found


def heading_entries(model):
    """(depth, level, text, chapter, ordinal) for each model heading; chapters split at level 1 and nesting follows level order."""
    entries = []; stack = []; chapter = 0
    for block in model:
        if block['kind'] != 'heading': continue
        level = block['level']
        if level == 1: chapter += 1
        while stack and stack[-1] >= level: stack.pop()
        stack.append(level)
        entries.append((len(stack), level, block['text'], chapter, len(entries) + 1))
    return entries


def table_rows(table):
    parts = container(table, XHTML + 'table', [XHTML + 'thead', XHTML + 'tbody'])
    rows = []
    for group, cell in zip(parts, ('th', 'td')):
        children = list(group)
        require(blank(group.text) and blank(group.tail) and not group.attrib and children and (cell == 'td' or len(children) == 1), 'EPUB table group differs')
        for row in children:
            cells = container(row, XHTML + 'tr', [XHTML + cell] * len(row))
            require(cells, 'EPUB table row is empty')
            rows.append([leaf(c, XHTML + cell) for c in cells])
    return rows


def chapter_blocks(body, counter, media, used):
    """The ordered model blocks of one chapter: heading, paragraph, table and image elements only, with exact section identifiers."""
    require(blank(body.text) and [c.tag for c in body] == [XHTML + 'section'], 'EPUB chapter must hold exactly one top-level section')
    result = []
    def section(node, depth):
        require(depth <= MAX_DEPTH, 'EPUB section nesting exceeds the supported depth')
        counter[0] += 1; ordinal = counter[0]
        require(node.get('class', '')[:5] == 'level' and node.get('class', '')[5:].isdigit() and set(node.attrib) == {'id', 'class'}
                and node.get('id') == f'section-{ordinal}' and blank(node.text) and blank(node.tail), 'EPUB section identity differs')
        level = int(node.get('class')[5:]); children = list(node)
        require(1 <= level <= 3 and children and children[0].tag == XHTML + f'h{level}', 'EPUB section heading differs')
        result.append({'kind': 'heading', 'level': level, 'text': leaf(children[0], XHTML + f'h{level}')})
        for child in children[1:]:
            if child.tag == XHTML + 'section': section(child, depth + 1)
            elif child.tag == XHTML + 'table': result.append({'kind': 'table', 'rows': table_rows(child)})
            elif child.tag == XHTML + 'p':
                require(not child.attrib and blank(child.tail), 'EPUB paragraph attributes differ')
                if len(child):
                    require(len(child) == 1 and blank(child.text) and child[0].tag == XHTML + 'img' and len(child[0]) == 0 and blank(child[0].tail), 'EPUB image paragraph differs')
                    image = child[0]; attrib = dict(image.attrib)
                    source = IMAGE_SOURCE.fullmatch(attrib.get('src', '')); width = IMAGE_WIDTH.fullmatch(attrib.get('style', ''))
                    require(set(attrib) == {'src', 'style', 'alt'} and source is not None and width is not None, 'EPUB image attributes differ (only an internal PNG with an explicit width is supported)')
                    name = 'EPUB/media/file' + source[1] + '.png'
                    require(name in media, 'EPUB image refers to a missing package member')
                    used.add(name)
                    result.append({'kind': 'image', 'alt': attrib['alt'], 'sha256': hashlib.sha256(media[name]).hexdigest(), 'widthMm': float(width[1])})
                else: result.append({'kind': 'paragraph', 'text': child.text or ''})
            else: fail('VERIFICATION_FAILED', 'EPUB chapter element outside the reviewed structure: ' + child.tag.rsplit('}', 1)[-1])
    section(body[0], 1)
    return result


def page(data, name, language, title, body_type, stylesheet, heading=None):
    root = xml_part(data, name, doctype=True)
    head, body = container(root, XHTML + 'html', [XHTML + 'head', XHTML + 'body'], {'lang': language, XMLLANG: language})
    meta_charset, meta_generator, label, style, link = container(head, XHTML + 'head', [XHTML + t for t in ('meta', 'meta', 'title', 'style', 'link')])
    leaf(meta_charset, XHTML + 'meta', {'charset': 'utf-8'}); leaf(meta_generator, XHTML + 'meta', {'name': 'generator', 'content': 'pandoc'})
    leaf(label, XHTML + 'title', text=heading if heading is not None else title)
    require(style.tag == XHTML + 'style' and not style.attrib and len(style) == 0 and blank(style.text) and blank(style.tail), 'EPUB inline style is unsupported')
    leaf(link, XHTML + 'link', {'rel': 'stylesheet', 'type': 'text/css', 'href': stylesheet})
    require(body.attrib == {OPS: body_type} and blank(body.tail), 'EPUB body type differs')
    return body


def toc_entries(ol, depth, out):
    require(ol.tag == XHTML + 'ol' and ol.attrib == {'class': 'toc'} and blank(ol.text) and blank(ol.tail) and len(ol) and depth <= MAX_DEPTH, 'EPUB table of contents list differs')
    for item in ol:
        children = list(item)
        require(item.tag == XHTML + 'li' and set(item.attrib) == {'id'} and blank(item.text) and blank(item.tail) and 1 <= len(children) <= 2
                and children[0].tag == XHTML + 'a' and set(children[0].attrib) == {'href'} and len(children[0]) == 0 and blank(children[0].tail),
                'EPUB table of contents entry differs')
        out.append((depth, children[0].text or '', children[0].get('href'), item.get('id')))
        if len(children) == 2: toc_entries(children[1], depth + 1, out)


def point_entries(parent, depth, out):
    for point in parent.findall(NCX + 'navPoint'):
        parts = list(point)
        require(set(point.attrib) == {'id'} and blank(point.text) and blank(point.tail) and len(parts) >= 2 and [p.tag for p in parts[:2]] == [NCX + 'navLabel', NCX + 'content']
                and all(p.tag == NCX + 'navPoint' for p in parts[2:]) and depth <= MAX_DEPTH + 1, 'EPUB NCX navigation point differs')
        label = container(parts[0], NCX + 'navLabel', [NCX + 'text'])[0]; source = parts[1].get('src')
        leaf(parts[1], NCX + 'content', {'src': source})
        out.append((depth, leaf(label, NCX + 'text'), source, point.get('id')))
        point_entries(point, depth + 1, out)


def package_report(data, title, language, model, metadata=None):
    """Check the EPUB bytes against the authored model; returns the facts the native readback comparison needs."""
    authors, description = declared(metadata)
    try:
        found = members(data)
        entries = heading_entries(model)
        chapters = sum(1 for e in entries if e[1] == 1)
        require(chapters >= 1 and entries[0][1] == 1, 'a report EPUB starts with a level 1 heading')
        chapter_names = [f'EPUB/text/ch{c:03d}.xhtml' for c in range(1, chapters + 1)]
        media = {n: b for n, b in found.items() if n.startswith('EPUB/media/')}
        require(all(MEDIA_NAME.fullmatch(n) for n in media), 'unexpected EPUB media member')
        expected = {'mimetype', 'META-INF/container.xml', 'META-INF/com.apple.ibooks.display-options.xml', 'EPUB/content.opf', 'EPUB/toc.ncx',
                    'EPUB/nav.xhtml', 'EPUB/text/title_page.xhtml', 'EPUB/styles/stylesheet1.css', *chapter_names, *media}
        require(set(found) == expected, 'unexpected EPUB package member: ' + ', '.join(sorted(set(found) ^ expected)))
        for name, digest in FIXED_PARTS.items():
            require(hashlib.sha256(found[name]).hexdigest() == digest, f'EPUB {name} differs from qualified Pandoc 3.12.1; review and requalify the native EPUB writer parts')
        # container.xml names the one package document; its bytes are pinned above and re-read here for the cross-reference.
        rootfile = container(xml_part(found['META-INF/container.xml'], 'container.xml'), CONTAINER + 'container', [CONTAINER + 'rootfiles'], {'version': '1.0'})
        leaf(container(rootfile[0], CONTAINER + 'rootfiles', [CONTAINER + 'rootfile'])[0], CONTAINER + 'rootfile',
             {'full-path': 'EPUB/content.opf', 'media-type': 'application/oebps-package+xml'})
        opf = xml_part(found['EPUB/content.opf'], 'content.opf')
        require(opf.tag == OPF + 'package' and dict(opf.attrib) == {'version': '3.0', XMLLANG: language, 'unique-identifier': 'epub-id-1', 'prefix': IBOOKS}
                and blank(opf.text) and [c.tag for c in opf] == [OPF + t for t in ('metadata', 'manifest', 'spine', 'guide')], 'EPUB package document differs')
        metadata, manifest, spine, guide = list(opf)
        wanted = [(DC + 'identifier', {'id': 'epub-id-1'}, None), (DC + 'title', {'id': 'epub-title-1'}, title), (DC + 'date', {'id': 'epub-date'}, FIXED_DATE),
                  (DC + 'language', {}, language),
                  # Pandoc writes each declared creator with the marc:relators role aut (author), then the description, before its own dates.
                  *[node for n, author in enumerate(authors, 1) for node in ((DC + 'creator', {'id': f'epub-creator-{n}'}, author),
                                                                           (OPF + 'meta', {'refines': f'#epub-creator-{n}', 'property': 'role', 'scheme': 'marc:relators'}, 'aut'))],
                  *([(DC + 'description', {}, description)] if description is not None else []),
                  (OPF + 'meta', {'property': 'dcterms:modified'}, FIXED_DATE),
                  *[(OPF + 'meta', {'property': p}, v) for p, v in ACCESSIBILITY]]
        require(blank(metadata.text) and not metadata.attrib and len(metadata) == len(wanted), 'EPUB package metadata differs')
        for node, (tag, attrib, text) in zip(metadata, wanted):
            leaf(node, tag, attrib, text)
        identifier = metadata[0].text or ''
        require(UUID.fullmatch(identifier) is not None, 'EPUB package identifier differs from the writer urn:uuid form')
        items = [('ncx', 'toc.ncx', 'application/x-dtbncx+xml', None), ('nav', 'nav.xhtml', 'application/xhtml+xml', 'nav'),
                 ('stylesheet1', 'styles/stylesheet1.css', 'text/css', None), ('title_page_xhtml', 'text/title_page.xhtml', 'application/xhtml+xml', None),
                 *[(f'ch{c:03d}_xhtml', f'text/ch{c:03d}.xhtml', 'application/xhtml+xml', None) for c in range(1, chapters + 1)]]
        require(blank(manifest.text) and not manifest.attrib and blank(manifest.tail) and all(i.tag == OPF + 'item' and len(i) == 0 and blank(i.tail) for i in manifest)
                and len(manifest) == len(items) + len(media), 'EPUB manifest differs')
        for node, (ident, href, kind, props) in zip(manifest, items):
            require(dict(node.attrib) == {'id': ident, 'href': href, 'media-type': kind, **({'properties': props} if props else {})}, 'EPUB manifest item differs: ' + ident)
        listed = {tuple(sorted(i.attrib.items())) for i in list(manifest)[len(items):]}
        require(len(listed) == len(media) and listed == {tuple(sorted({'id': f'file{MEDIA_NAME.fullmatch(n)[1]}_png', 'href': n[5:], 'media-type': 'image/png'}.items())) for n in media},
                'EPUB manifest media differs from the package members')
        order = ['title_page_xhtml', *[f'ch{c:03d}_xhtml' for c in range(1, chapters + 1)]]
        require(blank(spine.text) and blank(spine.tail) and dict(spine.attrib) == {'toc': 'ncx'} and len(spine) == len(order), 'EPUB spine differs')
        for node, ident in zip(spine, order):
            leaf(node, OPF + 'itemref', {'idref': ident, **({'linear': 'yes'} if ident == 'title_page_xhtml' else {})})
        require(blank(guide.text) and len(guide) == 1 and not guide.attrib, 'EPUB guide differs')
        leaf(guide[0], OPF + 'reference', {'type': 'toc', 'title': title, 'href': 'nav.xhtml'})
        title_body = page(found['EPUB/text/title_page.xhtml'], 'title_page.xhtml', language, title, 'frontmatter', '../styles/stylesheet1.css')
        titlepage = container(title_body, XHTML + 'body', [XHTML + 'section'], {OPS: 'frontmatter'})[0]
        heading, *lines = container(titlepage, XHTML + 'section', [XHTML + 'h1', *[XHTML + 'p'] * len(authors)], {OPS: 'titlepage', 'class': 'titlepage'})
        leaf(heading, XHTML + 'h1', {'class': 'title'}, title)
        for line, author in zip(lines, authors): leaf(line, XHTML + 'p', {'class': 'author'}, author)
        # Navigation: the nested table of contents and the NCX both name every heading and its chapter anchor.
        nav_body = page(found['EPUB/nav.xhtml'], 'nav.xhtml', language, title, 'frontmatter', 'styles/stylesheet1.css')
        toc, landmarks = container(nav_body, XHTML + 'body', [XHTML + 'nav', XHTML + 'nav'], {OPS: 'frontmatter'})
        heading, ol = container(toc, XHTML + 'nav', [XHTML + 'h1', XHTML + 'ol'], {OPS: 'toc', 'role': 'doc-toc', 'id': 'toc'})
        leaf(heading, XHTML + 'h1', {'id': 'toc-title'}, title)
        wanted_toc = [(d, text, f'text/ch{c:03d}.xhtml#section-{k}', f'toc-li-{k}') for d, _, text, c, k in entries]
        got = []; toc_entries(ol, 1, got); require(got == wanted_toc, 'EPUB table of contents differs from the report headings')
        listing = container(landmarks, XHTML + 'nav', [XHTML + 'ol'], {OPS: 'landmarks', 'id': 'landmarks', 'hidden': 'hidden'})[0]
        item = container(listing, XHTML + 'ol', [XHTML + 'li'])[0]
        anchor = container(item, XHTML + 'li', [XHTML + 'a'])[0]
        leaf(anchor, XHTML + 'a', {'href': 'text/title_page.xhtml', OPS: 'titlepage'}, 'Title Page')
        ncx = xml_part(found['EPUB/toc.ncx'], 'toc.ncx')
        head_node, doc_title, nav_map = container(ncx, NCX + 'ncx', [NCX + 'head', NCX + 'docTitle', NCX + 'navMap'], {'version': '2005-1'})
        metas = container(head_node, NCX + 'head', [NCX + 'meta'] * 4)
        require([(m.get('name'), m.get('content')) for m in metas] == [('dtb:uid', identifier), ('dtb:depth', '1'), ('dtb:totalPageCount', '0'), ('dtb:maxPageNumber', '0')]
                and all(set(m.attrib) == {'name', 'content'} and len(m) == 0 and blank(m.tail) for m in metas), 'EPUB NCX metadata differs from the package identifier')
        leaf(container(doc_title, NCX + 'docTitle', [NCX + 'text'])[0], NCX + 'text', text=title)
        require(blank(nav_map.text) and not nav_map.attrib and all(p.tag == NCX + 'navPoint' for p in nav_map), 'EPUB NCX navigation map differs')
        points = []; point_entries(nav_map, 1, points)
        require(points == [(1, title, 'text/title_page.xhtml', 'navPoint-0'), *[(d, text, f'text/ch{c:03d}.xhtml#section-{k}', f'navPoint-{k}') for d, _, text, c, k in entries]],
                'EPUB NCX differs from the report headings')
        # Content: every chapter in spine order, section identifiers numbered continuously across chapters.
        blocks = []; counter = [0]; used = set()
        for name in chapter_names:
            base = name.rsplit('/', 1)[-1]
            body = page(found[name], base, language, title, 'bodymatter', '../styles/stylesheet1.css', heading=base)
            blocks += chapter_blocks(body, counter, media, used)
        from schemaxis.core.faults import SchemaxisError
        from .adaptor import png
        for name, body in media.items():
            try: png(body, name)
            except SchemaxisError as error: fail('VERIFICATION_FAILED', 'EPUB media is not the plain bounded PNG the report captured: ' + error.fault.message[-80:], name)
        require(blocks == model, 'EPUB ordered heading/text/table/image semantics differ')
        # Every media member is referenced by an image element (one file may serve several identical images), and none is left over.
        require(used == set(media), 'EPUB media membership differs from the images the chapters reference: ' + ', '.join(sorted(used ^ set(media))))
        return {'identifier': identifier, 'chapters': chapters, 'entries': len(found), 'media': {n[5:]: hashlib.sha256(b).hexdigest() for n, b in media.items()}}
    except (zipfile.BadZipFile, zipfile.LargeZipFile, ET.ParseError, KeyError, ValueError, OverflowError, EOFError, RuntimeError, NotImplementedError, zlib.error, UnicodeError, RecursionError, struct.error) as error:
        fail('VERIFICATION_FAILED', 'invalid EPUB package: ' + type(error).__name__ + ': ' + str(error)[:200])


def text_of(items):
    """Plain text of Pandoc readback inlines; only words and single spaces are accepted, never a break, span or markup."""
    result = ''
    for item in items:
        require(isinstance(item, dict), 'unexpected native EPUB readback inline')
        if item.get('t') == 'Str' and type(item.get('c')) is str: result += item['c']
        else:
            require(item == {'t': 'Space'}, 'unexpected native EPUB readback inline: ' + str(item.get('t')))
            result += ' '
    return result


def meta_text(meta, key):
    value = meta.get(key)
    require(isinstance(value, dict) and value.get('t') == 'MetaInlines' and isinstance(value.get('c'), list) and set(value) == {'t', 'c'}, f'native EPUB readback {key} differs')
    return text_of(value['c'])


ATTR = ['', [], []]


def readback_table(content):
    require(len(content) == 6 and content[0] == ATTR and content[1] == [None, []] and content[5] == [ATTR, []] and content[3][0] == ATTR and len(content[3][1]) == 1
            and len(content[4]) == 1 and content[4][0][0] == ATTR and content[4][0][1] == 0 and content[4][0][2] == [] and content[4][0][3],
            'native EPUB table must be one header row, one body group of data rows and no footer')
    rows = [*content[3][1], *content[4][0][3]]
    require(all(spec == [{'t': 'AlignDefault'}, {'t': 'ColWidthDefault'}] for spec in content[2]) and len(content[2]) == len(rows[0][1]), 'native EPUB table columns differ')
    def cell(value):
        require(value[:1] == [ATTR] and value[1] == {'t': 'AlignDefault'} and value[2:4] == [1, 1] and len(value[4]) == 1 and value[4][0]['t'] in ('Plain', 'Para'),
                'native EPUB table spans/cell structure differs')
        return text_of(value[4][0]['c'])
    result = []
    for row in rows:
        require(row[0] == ATTR and len(row[1]) == len(rows[0][1]), 'native EPUB table row differs')
        result.append([cell(c) for c in row[1]])
    return {'kind': 'table', 'rows': result}


def readback_report(value, title, language, facts, model, metadata=None):
    """Compare Pandoc's own fresh EPUB readback with the model and the independently inspected package."""
    try:
        require(isinstance(value, dict) and isinstance(value.get('meta'), dict) and isinstance(value.get('blocks'), list), 'native EPUB readback shape differs')
        meta = value['meta']
        authors, description = declared(metadata)
        require(set(meta) == {'date', 'identifier', 'language', 'title', *(['author'] if authors else []), *(['description'] if description is not None else [])},
                'native EPUB readback metadata differs from the declared metadata')
        # Pandoc 3.12.1's EPUB reader returns the creators in reverse of their package (and declared) order; the order that matters is checked in the package above.
        if authors: require(meta_authors(meta['author']) == authors[::-1], 'native EPUB readback authors differ from the declared authors')
        if description is not None: require(meta_text(meta, 'description') == description, 'native EPUB readback description differs from the declared description')
        require(meta_text(meta, 'title') == title and meta_text(meta, 'language') == language and meta_text(meta, 'identifier') == facts['identifier']
                and meta_text(meta, 'date') == FIXED_DATE, 'native EPUB readback title, language or identifier differs')
        chapters = facts['chapters']; blocks = value['blocks']
        require(len(blocks) == 1 + 2 * chapters, 'native EPUB readback chapter count differs')
        def marker(block, name): require(block == {'t': 'Para', 'c': [{'t': 'Span', 'c': [[name, [], []], []]}]}, 'native EPUB readback file marker differs: ' + name)
        marker(blocks[0], 'title_page.xhtml')
        result = []; counter = [0]
        def section(block, base, depth):
            require(depth <= MAX_DEPTH and isinstance(block, dict) and block.get('t') == 'Div', 'native EPUB readback section differs')
            counter[0] += 1; attr, items = block['c']
            head = items[0] if items else None
            require(isinstance(head, dict) and head.get('t') == 'Header', 'native EPUB readback section heading differs')
            level = head['c'][0]
            require(attr == [f'{base}_section-{counter[0]}', ['section', f'level{level}'], []] and head['c'][1] == ATTR and type(level) is int and 1 <= level <= 3,
                    'native EPUB readback section identity differs')
            result.append({'kind': 'heading', 'level': level, 'text': text_of(head['c'][2])})
            for item in items[1:]:
                kind = item.get('t'); content = item.get('c')
                if kind == 'Div': section(item, base, depth + 1)
                elif kind == 'Table': result.append(readback_table(content))
                elif kind in ('Para', 'Plain'):
                    if len(content) == 1 and content[0].get('t') == 'Image':
                        attr_, alt, target = content[0]['c']
                        source = re.fullmatch(r'media/file([0-9]+)\.png', target[0]) if target[1:] == [''] else None
                        width = IMAGE_WIDTH.fullmatch(attr_[2][0][1]) if attr_[:2] == ['', []] and len(attr_[2]) == 1 and attr_[2][0][0] == 'style' else None
                        require(source is not None and width is not None and target[0] in facts['media'], 'native EPUB readback image differs')
                        result.append({'kind': 'image', 'alt': text_of(alt), 'sha256': facts['media'][target[0]], 'widthMm': float(width[1])})
                    else: result.append({'kind': 'paragraph', 'text': text_of(content)})
                else: fail('VERIFICATION_FAILED', 'unexpected native EPUB readback block: ' + str(kind))
        for number in range(1, chapters + 1):
            base = f'ch{number:03d}.xhtml'; marker(blocks[2 * number - 1], base); section(blocks[2 * number], base, 1)
        require(result == model, 'fresh native EPUB readback ordered semantics differ')
    except (KeyError, IndexError, TypeError, ValueError, AttributeError, RecursionError) as error:
        fail('VERIFICATION_FAILED', 'invalid native EPUB readback: ' + type(error).__name__ + ': ' + str(error)[:200])
