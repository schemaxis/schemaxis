"""Deterministic hand-built EPUB 3 packages for the EPUBCheck host tests, fixtures and native qualifier.

The packages are written from first principles (no Schemaxis import, no EPUB library). Each defective variant is designed with
one stated fault, so the expected EPUBCheck message identifiers come from the design, not from running the adaptor:

* ``valid``: a two-file reflowable book; EPUBCheck reports nothing.
* ``missing_title``: no dc:title and a spine itemref naming no manifest item (RSC-005 twice, OPF-049, RSC-011 from the nav).
* ``missing_image``: a reference to an absent image (RSC-007, error) and an unclosed element (RSC-016, fatal).
* ``bad_date``: dc:date "yesterday" (OPF-053, a warning, rejected only under --failonwarnings).
* ``remote_image``: an image at an http URL that is not a declared remote resource (OPF-014 and RSC-006).
* ``epub2``: a direct native probe of external DTD resolution (see its docstring); never a host-admitted publication.
"""
import io
import struct
import zipfile
import zlib

CONTAINER = ('<?xml version="1.0"?>\n<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles>'
             '<rootfile full-path="EPUB/package.opf" media-type="application/oebps-package+xml"/></rootfiles></container>\n')
NAV = ('<?xml version="1.0" encoding="UTF-8"?>\n<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops"><head><title>Contents</title></head>'
       '<body><nav epub:type="toc"><ol><li><a href="chapter.xhtml">One</a></li></ol></nav></body></html>\n')
DATE = (1980, 1, 1, 0, 0, 0)


def opf(title='Tiny', spine='chapter', extra='', date='', creator=''):
    return ('<?xml version="1.0" encoding="UTF-8"?>\n<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="id" xml:lang="en">\n'
            '<metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:identifier id="id">urn:uuid:12345678-1234-1234-1234-123456789abc</dc:identifier>'
            + ('<dc:title>%s</dc:title>' % title if title else '') + date + creator + '<dc:language>en</dc:language>'
            '<meta property="dcterms:modified">2026-01-01T00:00:00Z</meta></metadata>\n'
            '<manifest><item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>'
            '<item id="chapter" href="chapter.xhtml" media-type="application/xhtml+xml"/>' + extra + '</manifest>\n'
            '<spine><itemref idref="%s"/></spine></package>\n' % spine)


def chapter(body='<p>Hello.</p>'):
    return ('<?xml version="1.0" encoding="UTF-8"?>\n<html xmlns="http://www.w3.org/1999/xhtml"><head><title>One</title></head><body>%s</body></html>\n' % body)


def package(members, order=None):
    """Deterministic ZIP: ``members`` is a list of (name, bytes or str, deflated); mimetype is first and stored."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w') as archive:
        for name, data, deflated in members:
            info = zipfile.ZipInfo(name, DATE)
            info.compress_type = zipfile.ZIP_DEFLATED if deflated else zipfile.ZIP_STORED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, data)
    return buffer.getvalue()


def epub(opf_text=None, chapter_text=None, extra=()):
    return package([('mimetype', 'application/epub+zip', False), ('META-INF/container.xml', CONTAINER, True), ('EPUB/package.opf', opf_text or opf(), True),
                    ('EPUB/nav.xhtml', NAV, True), ('EPUB/chapter.xhtml', chapter_text or chapter(), True), *extra])


def valid():
    return epub()


def missing_title():
    return epub(opf_text=opf(title=None, spine='missing'))


def missing_image():
    return epub(chapter_text=chapter('<p><img src="missing.png" alt="x"/><b>unclosed</p>'))


def bad_date():
    return epub(opf_text=opf(date='<dc:date>yesterday</dc:date>'))


def remote_image():
    return epub(chapter_text=chapter('<p><img src="http://127.0.0.1:9/x.png" alt="x"/></p>'))


def png():
    def chunk(kind, data):
        return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data) & 0xffffffff)
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', 1, 1, 8, 2, 0, 0, 0)) + chunk(b'IDAT', zlib.compress(b'\x00\xff\x00\x00'))
            + chunk(b'IEND', b''))


def rich():
    """Two spine chapters, a stylesheet and a one-pixel PNG: nine-file valid EPUB 3 with every resource referenced."""
    extra = ('<item id="css" href="style.css" media-type="text/css"/><item id="two" href="two.xhtml" media-type="application/xhtml+xml"/>'
             '<item id="pic" href="pic.png" media-type="image/png"/>')
    package_text = opf(extra=extra).replace('<spine><itemref idref="chapter"/>', '<spine><itemref idref="chapter"/><itemref idref="two"/>')
    first = chapter('<p>Hello.</p><p><img src="pic.png" alt="One red pixel"/></p>').replace('</title>', '</title><link rel="stylesheet" type="text/css" href="style.css"/>')
    return epub(opf_text=package_text, chapter_text=first, extra=[('EPUB/style.css', 'p { margin: 0 }\n', True), ('EPUB/two.xhtml', chapter('<h1>Two</h1><p>More.</p>'), True),
                                                                 ('EPUB/pic.png', png(), False)])


def epub2(doctype, version=2, content='c.xhtml'):
    """A minimal EPUB 2 (``version=3`` for EPUB 3) whose one content document carries ``doctype``: a probe of EPUBCheck's external DTD resolution.

    It is not admitted by the host preflight when ``doctype`` names a SYSTEM identifier outside the checker's catalogue, so it is only for direct native probes.
    """
    if version == 2:
        package_text = ('<?xml version="1.0"?><package xmlns="http://www.idpf.org/2007/opf" unique-identifier="id" version="2.0"><metadata xmlns:dc="http://purl.org/dc/elements/1.1/">'
                        '<dc:title>T</dc:title><dc:language>en</dc:language><dc:identifier id="id">urn:x:1</dc:identifier></metadata><manifest>'
                        '<item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/><item id="c" href="c.xhtml" media-type="application/xhtml+xml"/></manifest>'
                        '<spine toc="ncx"><itemref idref="c"/></spine></package>')
        navigation = ('OEBPS/toc.ncx', '<?xml version="1.0"?><ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1"><head><meta name="dtb:uid" content="urn:x:1"/></head>'
                      '<docTitle><text>T</text></docTitle><navMap><navPoint id="n" playOrder="1"><navLabel><text>C</text></navLabel><content src="c.xhtml"/></navPoint></navMap></ncx>')
    else:
        package_text = ('<?xml version="1.0"?><package xmlns="http://www.idpf.org/2007/opf" unique-identifier="id" version="3.0"><metadata xmlns:dc="http://purl.org/dc/elements/1.1/">'
                        '<dc:identifier id="id">urn:x:1</dc:identifier><dc:title>T</dc:title><dc:language>en</dc:language><meta property="dcterms:modified">2026-01-01T00:00:00Z</meta></metadata>'
                        '<manifest><item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/><item id="c" href="c.xhtml" media-type="application/xhtml+xml"/></manifest>'
                        '<spine><itemref idref="c"/></spine></package>')
        navigation = ('OEBPS/nav.xhtml', '<?xml version="1.0"?><html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops"><head><title>N</title></head>'
                      '<body><nav epub:type="toc"><ol><li><a href="c.xhtml">C</a></li></ol></nav></body></html>')
    container = CONTAINER.replace('EPUB/package.opf', 'OEBPS/content.opf')
    name, text = content, '<?xml version="1.0"?>\n' + doctype + '\n<html xmlns="http://www.w3.org/1999/xhtml"><head><title>C</title></head><body><p>x</p></body></html>'
    return package([('mimetype', 'application/epub+zip', False), ('META-INF/container.xml', container, True), ('OEBPS/content.opf', package_text.replace('c.xhtml', name), True),
                    (navigation[0], navigation[1].replace('c.xhtml', name), True), ('OEBPS/' + name, text, True)])


EXPECTED = {
    'valid': {'ids': [], 'counts': (0, 0, 0)},
    'missing_title': {'ids': ['OPF-049', 'RSC-005', 'RSC-005', 'RSC-011'], 'counts': (0, 4, 0)},
    'missing_image': {'ids': ['RSC-007', 'RSC-016'], 'counts': (1, 1, 0)},
    'bad_date': {'ids': ['OPF-053'], 'counts': (0, 0, 1)},
    'remote_image': {'ids': ['OPF-014', 'RSC-006'], 'counts': (0, 2, 0)}}
FIXTURE_FILES = {'tiny-valid.epub': valid, 'rich-valid.epub': rich, 'invalid-package.epub': missing_title, 'missing-image.epub': missing_image, 'warning-date.epub': bad_date}


def with_member(data, name, content, deflated=True):
    """The same ZIP plus one extra member (an unrelated resource or a hostile one for preflight tests)."""
    source = zipfile.ZipFile(io.BytesIO(data))
    members = [(i.filename, source.read(i.filename), i.compress_type == zipfile.ZIP_DEFLATED) for i in source.infolist()]
    return package(members + [(name, content, deflated)])


def raw_zip(entries):
    """Hand-framed ZIP (stored members only) for names and attributes ``zipfile`` would refuse or normalise.

    ``entries`` are (name bytes, data, flag bits, external attribute, create system) tuples.
    """
    body, central = b'', b''
    for name, data, flags, external, system in entries:
        crc = zipfile.crc32(data) & 0xffffffff
        local = struct.pack('<IHHHHHIIIHH', 0x04034b50, 20, flags, 0, 0, 0x21, crc, len(data), len(data), len(name), 0)
        central += struct.pack('<IHHHHHHIIIHHHHHII', 0x02014b50, (system << 8) | 20, 20, flags, 0, 0, 0x21, crc, len(data), len(data), len(name), 0, 0, 0, 0,
                               external, len(body)) + name
        body += local + name + data
    end = struct.pack('<IHHHHIIH', 0x06054b50, 0, 0, len(entries), len(entries), len(central), len(body), 0)
    return body + central + end


def replace_member(book, name, data):
    """The same ZIP with the bytes of one member replaced (for encodings and content a text helper cannot write)."""
    source = zipfile.ZipFile(io.BytesIO(book))
    return package([(i.filename, data if i.filename == name else source.read(i.filename), i.compress_type == zipfile.ZIP_DEFLATED) for i in source.infolist()])
