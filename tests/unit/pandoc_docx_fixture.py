"""Complete synthetic DOCX packages in the shape of Pandoc's writer, for inspection tests (not Pandoc output).

The inspector binds the fixed writer parts to digests of real Pandoc 3.12.1 output, so tests check a synthetic
package with the digests of its own placeholder parts patched in. Everything else (members, relationships,
content types, core properties, body grammar) is checked by the production code unchanged.
"""
import hashlib
import io
import struct
from unittest.mock import patch
import zipfile
import zlib

from schemaxis.adaptors.pandoc import inspection

W = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
REL = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships/'
PKG = 'http://schemas.openxmlformats.org/package/2006/relationships'
TYPES = 'http://schemas.openxmlformats.org/package/2006/content-types'
OFFICE = 'application/vnd.openxmlformats-officedocument.'
ROOT = ('xmlns:w="%s" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
        'xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing" '
        'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
        'xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture"' % W)

FIXED = {name: ('<fixed part="%s"/>' % name).encode() for name in inspection.DOCX_FIXED_PARTS}
FIXED['word/_rels/footnotes.xml.rels'] = b'<Relationships xmlns="%s"/>' % PKG.encode()


def png(width=8, height=4, shade=0):
    def chunk(kind, body): return struct.pack('>I', len(body)) + kind + body + struct.pack('>I', zlib.crc32(kind + body))
    rows = b''.join(b'\x00' + bytes([shade, 0, 0]) * width for _ in range(height))
    return b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0)) + chunk(b'IDAT', zlib.compress(rows)) + chunk(b'IEND', b'')


def relationships(entries, namespace=PKG):
    return ('<Relationships xmlns="%s">%s</Relationships>' % (namespace, ''.join(
        '<Relationship Id="%s" Type="%s" Target="%s"/>' % entry for entry in entries))).encode()


def image_paragraph(rid='rId11', alt='Alt text', cx=288000, cy=144000, style='FirstParagraph', shape='inline', blip='<a:blip r:embed="%s"/>'):
    """Native-shaped picture paragraph. `shape` may be replaced to forge floating (anchored) pictures."""
    return ('<w:p><w:pPr><w:pStyle w:val="%s"/></w:pPr><w:r><w:drawing><wp:%s><wp:extent cx="%d" cy="%d"/><wp:effectExtent b="0" l="0" r="0" t="0"/>'
            '<wp:docPr descr="%s" id="12" name="Picture"/><a:graphic><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture">'
            '<pic:pic><pic:nvPicPr><pic:cNvPr id="13" name="Picture"/><pic:cNvPicPr/></pic:nvPicPr><pic:blipFill>%s<a:stretch><a:fillRect/></a:stretch></pic:blipFill>'
            '<pic:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="%d" cy="%d"/></a:xfrm></pic:spPr></pic:pic></a:graphicData></a:graphic></wp:%s></w:drawing></w:r></w:p>'
            % (style, shape, cx, cy, alt, blip % rid if '%s' in blip else blip, cx, cy, shape))


def core(title):
    return ('<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" xmlns:dc="http://purl.org/dc/elements/1.1/" '
            'xmlns:dcterms="http://purl.org/dc/terms/" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"><dc:title>%s</dc:title><dc:creator></dc:creator>'
            '<cp:keywords></cp:keywords><dcterms:created xsi:type="dcterms:W3CDTF">1970-01-01T00:00:00Z</dcterms:created>'
            '<dcterms:modified xsi:type="dcterms:W3CDTF">1970-01-01T00:00:00Z</dcterms:modified></cp:coreProperties>' % title).encode()


def parts(document, title='Report', media=None):
    """Every member of a reference package; `media` maps member names below word/media to PNG bytes."""
    media = media or {}
    ids = {name: 'rId%d' % (11 + i) for i, name in enumerate(media)}
    fixed_rels = [('rId%d' % (i + 1), kind, target) for i, (kind, target) in enumerate(inspection.DOCUMENT_RELATIONSHIPS.items())]
    overrides = {**inspection.CONTENT_OVERRIDES, **{'/word/media/' + n: 'image/png' for n in media}}
    return {
        '[Content_Types].xml': ('<Types xmlns="%s">%s%s</Types>' % (TYPES,
            ''.join('<Default Extension="%s" ContentType="%s"/>' % item for item in inspection.CONTENT_DEFAULTS.items()),
            ''.join('<Override PartName="%s" ContentType="%s"/>' % item for item in overrides.items()))).encode(),
        '_rels/.rels': relationships([('rId%d' % (i + 1), kind, target) for i, (kind, target) in enumerate(inspection.ROOT_RELATIONSHIPS.items())]),
        'word/_rels/document.xml.rels': relationships([*fixed_rels, *[(ids[n], REL + 'image', 'media/' + n) for n in media]]),
        'word/document.xml': ('<w:document %s><w:body>%s</w:body></w:document>' % (ROOT, document)).encode(),
        'docProps/core.xml': core(title), **FIXED, **{'word/media/' + n: data for n, data in media.items()}}


def build(document, title='Report', media=None, change=None, add=None, drop=()):
    members = {k: v for k, v in parts(document, title, media).items() if k not in drop}
    members.update(change or {}); members.update(add or {})
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name, data in members.items(): archive.writestr(name, data)
    return buffer.getvalue()


def check(data, title, model):
    """Run the production DOCX inspector with this fixture's placeholder parts treated as the reviewed digests."""
    digests = {name: hashlib.sha256(data).hexdigest() for name, data in FIXED.items()}
    with patch.object(inspection, 'DOCX_FIXED_PARTS', digests): inspection.docx_report(data, title, model)
