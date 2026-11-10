# Copyright (C) 2026 David L F Gaden
"""Independent HTML/OOXML checks plus fresh native semantic AST readback."""
import base64
import hashlib
from html.parser import HTMLParser
import io
from pathlib import Path, PurePosixPath
import re
import xml.etree.ElementTree as ET
import zipfile
import zlib

from schemaxis.errors import fail

# Reviewed native Pandoc 3.12.1 default HTML stylesheet (2701 UTF-8 bytes).
# An upstream style change requires review and fresh native qualification.
# Keep this in trusted code: an editable run receipt cannot approve new CSS.
QUALIFIED_STYLESHEET_SHA256 = '9466a348764bb1184fd84927af08d92a0b7a72627a5a27f374c1cdb7c34d5714'
# Reviewed native Pandoc 3.12.1 default DOCX writer parts whose bytes never depend on the report: styles decide
# what Word displays, the theme supplies fonts and colours those styles refer to, and the remaining parts are
# fixed settings and empty containers. A replaced or edited part could hide reported text from the body checks,
# so each is bound to its reviewed digest in trusted code; an editable run receipt cannot approve new content.
# An upstream change requires review and fresh native qualification.
DOCX_FIXED_PARTS = {
    'word/styles.xml': '0b50bd5f967caf4f2a08060ed27285bc57de1beee599f97ccef9a8268086f2f3',
    'word/theme/theme1.xml': '287e41f62eb4a943f333f886d04665d31fb7397ec8f48c589a055c9f1d0cecbf',
    'word/numbering.xml': '4bed7a3a5ff0d9b6d251b6c0ce4de864f5261f5c40cf32e3a8e4d4e682284e39',
    'word/settings.xml': 'de15c1c1b3fb28a86dd9991f8343ae7e0fb14fc0e7c5187c32c1c58fb13f0f1c',
    'word/fontTable.xml': '855d35ae8c32c3d324061d647f19946c5bb587086f20534898db100b63e7c20f',
    'word/webSettings.xml': '85ec1f6e8d13bcbdbf7cf928ed9dc75f02bc0600be57bd26c74a3eb2de6dfb4f',
    'word/footnotes.xml': '0862050ac498039adcb369c821645a486c0dd66d3edf3ed464eb7da29ca4b67a',
    'word/comments.xml': '7b87229d5af1f34f0fad2e50382eb6c8080c9afa29b641c4ae93e98529d0a320',
    'word/_rels/footnotes.xml.rels': '81a8f2f71ac53d7c27a4b4086c521224ee37772dfe36a8f5016851ede2639b32',
    'docProps/app.xml': '3af512c1d965d98f87dfdb9d3638ab668264dea6f73aed3ea005f1aa6b533359',
    'docProps/custom.xml': '9c2a5541f9dd5d568d7c5841e795e575e874ea07adb07acc8bc6fb188f8755c3'}


def require(condition, message):
    if not condition: fail('VERIFICATION_FAILED', message)


class Node:
    def __init__(self, tag='', attrs=()):
        require(len(attrs)==len(dict(attrs)),'duplicate HTML attributes unsupported')
        self.tag=tag; self.attrs=dict(attrs); self.children=[]
    def text(self): return ''.join(c if isinstance(c,str) else c.text() for c in self.children)
    def all(self, tag):
        for child in self.children:
            if isinstance(child,Node):
                if child.tag==tag: yield child
                yield from child.all(tag)


class HTML(HTMLParser):
    def __init__(self): super().__init__(convert_charrefs=True); self.root=Node(); self.stack=[self.root]
    def handle_starttag(self, tag, attrs):
        node=Node(tag,attrs); self.stack[-1].children.append(node)
        if tag not in ('img','meta','link','br','hr','input','source','wbr','area','base','col','embed','param','track'):
            require(len(self.stack)<=32,'HTML element nesting exceeds the supported depth'); self.stack.append(node)
    def handle_comment(self, data): fail('VERIFICATION_FAILED','HTML comments are unsupported')
    def handle_pi(self, data): fail('VERIFICATION_FAILED','HTML processing instructions are unsupported')
    def unknown_decl(self, data): fail('VERIFICATION_FAILED','HTML marked sections are unsupported')
    def handle_decl(self, decl): require(decl.lower()=='doctype html','HTML document type differs')
    def handle_startendtag(self, tag, attrs):
        node=Node(tag,attrs); self.stack[-1].children.append(node)
    def handle_endtag(self, tag):
        if len(self.stack)>1:
            require(self.stack[-1].tag==tag,'malformed native HTML nesting'); self.stack.pop()
    def handle_data(self,data): self.stack[-1].children.append(data)


# Containers whose direct text or children the semantic reader never inspects. Browsers
# still render stray text, so each must hold only whitespace and the listed elements.
HTML_CONTAINERS={'html':('head','body'),'head':('meta','title','style'),'body':('header','h1','h2','h3','p','table'),
                 'header':('h1','p'),'table':('thead','tbody'),'thead':('tr',),'tbody':('tr',),'tr':('td','th')}


def html_structure(node):
    allowed=HTML_CONTAINERS.get(node.tag)
    if node.tag=='' : allowed=('html',)
    if allowed is not None:
        for child in node.children:
            if isinstance(child,str): require(not child.strip(),'HTML text outside reportable elements: '+(node.tag or 'document'))
            else: require(child.tag in allowed,'HTML element outside the reviewed structure: '+child.tag+' in '+(node.tag or 'document'))
    for child in node.children:
        if isinstance(child,Node): html_structure(child)


def html_table(table):
    """One header row of `th` cells, then one body group of `td` cells; cells hold text only."""
    groups=[c for c in table.children if isinstance(c,Node)]
    require([g.tag for g in groups]==['thead','tbody'],'HTML table requires exactly one header group then one body group')
    rows=[]
    for group,tag in zip(groups,('th','td')):
        group_rows=[r for r in group.children if isinstance(r,Node)]
        require(len(group_rows)==(1 if tag=='th' else len(group_rows)) and group_rows,'HTML table header must be exactly one row and the body nonempty')
        for row in group_rows:
            cells=[c for c in row.children if isinstance(c,Node)]
            require(cells and all(c.tag==tag for c in cells),'HTML table '+('header' if tag=='th' else 'body')+' row must hold only '+tag+' cells')
            require(all(isinstance(x,str) for c in cells for x in c.children),'HTML table cell holds nested elements')
            rows.append([c.text() for c in cells])
    return rows


def declared(metadata):
    """(authors in declared order, description or None) from a validated metadata declaration; an absent declaration declares neither."""
    metadata=metadata or {}
    return list(metadata.get('authors',[])), metadata.get('description')


def html_report(source,title,model,metadata=None):
    authors,description=declared(metadata)
    parser=HTML(); parser.feed(source); parser.close(); root=parser.root
    require(len(parser.stack)==1,'unclosed native HTML element')
    html_structure(root)
    require([n.tag for n in root.children if isinstance(n,Node)]==['html'],'standalone HTML must contain exactly one html element')
    html_nodes=[n for n in root.children if isinstance(n,Node)][0]
    require([n.tag for n in html_nodes.children if isinstance(n,Node)]==['head','body'],'standalone HTML requires exactly head then body')
    require([n.text() for n in root.all('title')]==[title], 'HTML browser title differs')
    require(not any(list(root.all(tag)) for tag in ('script','iframe','link','base','object','embed')),'HTML contains active content or external resources')
    for node in root.all('meta'):
        require(set(node.attrs)<= {'charset','name','content'} and node.attrs.get('name','') in ('','generator','viewport','author','description'),'HTML unexpected metadata or refresh')
    # Author and description meta elements are exactly the declared ones, in declared order; an undeclared, missing, repeated or stale one is refused.
    named=[(n.attrs['name'],n.attrs.get('content')) for n in root.all('meta') if n.attrs.get('name') in ('author','description')]
    require(named==[('author',a) for a in authors]+([('description',description)] if description is not None else []),'HTML author/description metadata differs from the declared metadata')
    styles=list(root.all('style'))
    require(len(styles)==1 and hashlib.sha256(styles[0].text().encode('utf-8')).hexdigest()==QUALIFIED_STYLESHEET_SHA256,
            'HTML default stylesheet differs from qualified Pandoc 3.12.1; review and requalify the native stylesheet')
    def outer(node):
        require(not any(k.lower().startswith('on') for k in node.attrs),'HTML event attributes unsupported')
        if node.tag=='html': require(set(node.attrs)<= {'xmlns','lang','xml:lang'},'HTML root attributes differ')
        if node.tag in ('head','title','style'): require(not node.attrs,'HTML head attributes differ')
        if node.tag=='head': require(all(not isinstance(c,Node) or c.tag in ('meta','title','style') for c in node.children),'HTML head resource unsupported')
        for child in node.children:
            if isinstance(child,Node): outer(child)
    outer(root)
    body=list(root.all('body')); require(len(body)==1,'standalone HTML body missing')
    result=[]; titles=[]
    allowed={'body':set(),'header':{'id'},'h1':{'id','class'},'h2':{'id'},'h3':{'id'},'p':set(),'table':set(),'thead':set(),'tbody':set(),'tr':set(),'td':set(),'th':set(),'img':{'src','alt','style'}}
    def grammar(node,parent=''):
        # A title-block author line is the one paragraph that carries a class; it must be a class author text-only paragraph inside header.
        permitted=allowed.get(node.tag,set())|({'class'} if node.tag=='p' and parent=='header' else set())
        require(node.tag in allowed and set(node.attrs)<=permitted,'unexpected HTML content/attribute: '+node.tag)
        for child in node.children:
            if isinstance(child,Node): grammar(child,node.tag)
    grammar(body[0])
    def visit(node):
        if node.tag=='header':
            # The title block is the title heading, then one text-only author line per declared author, in order.
            parts=[c for c in node.children if isinstance(c,Node)]
            require([c.tag for c in parts]==['h1']+['p']*len(authors),'HTML title block differs from the declared title and authors')
            require(all(c.attrs=={'class':'author'} and all(isinstance(x,str) for x in c.children) for c in parts[1:]),'HTML author line differs')
            require([c.text() for c in parts[1:]]==authors,'HTML visible author list differs from the declared authors')
            titles.extend(n.text() for n in node.all('h1')); return
        if node.tag in ('h1','h2','h3'):
            result.append({'kind':'heading','level':int(node.tag[1]),'text':node.text()}); return
        if node.tag=='table':
            result.append({'kind':'table','rows':html_table(node)}); return
        if node.tag=='p':
            images=list(node.all('img'))
            if images:
                require(len(images)==1 and not node.text().strip(),'HTML image paragraph differs'); image=images[0]
                uri=image.attrs.get('src',''); require(uri.startswith('data:image/png;base64,'),'HTML image is not standalone embedded PNG')
                try: data=base64.b64decode(uri.split(',',1)[1],validate=True)
                except ValueError: fail('VERIFICATION_FAILED','invalid HTML image encoding')
                style=image.attrs.get('style',''); width=re.fullmatch(r'width:\s*([0-9]+(?:\.[0-9]+)?)mm;?',style)
                require(width is not None,'HTML explicit image width missing')
                result.append({'kind':'image','alt':image.attrs.get('alt'),'sha256':hashlib.sha256(data).hexdigest(),'widthMm':float(width[1])})
            else: result.append({'kind':'paragraph','text':node.text()})
            return
        require(node.tag=='body','unexpected HTML body element: '+node.tag)
        for child in node.children:
            if isinstance(child,Node): visit(child)
    visit(body[0]); require(titles==[title],'HTML visible report title differs')
    require(result==model,'HTML ordered heading/text/table/image semantics differ')


NS={'w':'http://schemas.openxmlformats.org/wordprocessingml/2006/main',
    'r':'http://schemas.openxmlformats.org/officeDocument/2006/relationships',
    'a':'http://schemas.openxmlformats.org/drawingml/2006/main',
    'wp':'http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing'}


# Reviewed package structure of Pandoc's default DOCX writer. The member set, every relationship (type and
# target), every content type and each fixed part's bytes are closed: macros, embedded objects, headers/footers,
# custom XML, re-pointed relationships, unreferenced parts and edited auxiliary parts are hidden content for
# this closed report and are refused. Only declared PNG media varies, and it is bound to the image paragraphs.
REL = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships/'
PACKAGE_REL = 'http://schemas.openxmlformats.org/package/2006/relationships'
CORE_REL = PACKAGE_REL + '/metadata/core-properties'
CONTENT_TYPES = 'http://schemas.openxmlformats.org/package/2006/content-types'
ROOT_RELATIONSHIPS = {REL + 'officeDocument': 'word/document.xml', REL + 'extended-properties': 'docProps/app.xml',
                      CORE_REL: 'docProps/core.xml', REL + 'custom-properties': 'docProps/custom.xml'}
DOCUMENT_RELATIONSHIPS = {REL + 'numbering': 'numbering.xml', REL + 'styles': 'styles.xml', REL + 'settings': 'settings.xml',
                          REL + 'webSettings': 'webSettings.xml', REL + 'fontTable': 'fontTable.xml',
                          REL + 'theme': 'theme/theme1.xml', REL + 'footnotes': 'footnotes.xml', REL + 'comments': 'comments.xml'}
OFFICE = 'application/vnd.openxmlformats-officedocument.'
CONTENT_DEFAULTS = {'xml': 'application/xml', 'rels': 'application/vnd.openxmlformats-package.relationships+xml',
                    'odttf': OFFICE + 'obfuscatedFont'}
CONTENT_OVERRIDES = {
    '/word/document.xml': OFFICE + 'wordprocessingml.document.main+xml', '/word/styles.xml': OFFICE + 'wordprocessingml.styles+xml',
    '/word/numbering.xml': OFFICE + 'wordprocessingml.numbering+xml', '/word/settings.xml': OFFICE + 'wordprocessingml.settings+xml',
    '/word/webSettings.xml': OFFICE + 'wordprocessingml.webSettings+xml', '/word/fontTable.xml': OFFICE + 'wordprocessingml.fontTable+xml',
    '/word/footnotes.xml': OFFICE + 'wordprocessingml.footnotes+xml', '/word/comments.xml': OFFICE + 'wordprocessingml.comments+xml',
    '/word/theme/theme1.xml': OFFICE + 'theme+xml', '/docProps/app.xml': OFFICE + 'extended-properties+xml',
    '/docProps/custom.xml': OFFICE + 'custom-properties+xml', '/docProps/core.xml': 'application/vnd.openxmlformats-package.core-properties+xml'}
MEDIA = re.compile(r'media/[A-Za-z0-9_-]+\.png')
# Pandoc reports only the title; creator and keywords are empty and the dates are fixed under --sandbox.
DESCRIPTION_TAG = '{http://purl.org/dc/elements/1.1/}description'
CORE_TAGS = ['{http://purl.org/dc/elements/1.1/}title', '{http://purl.org/dc/elements/1.1/}creator',
             '{http://schemas.openxmlformats.org/package/2006/metadata/core-properties}keywords',
             '{http://purl.org/dc/terms/}created', '{http://purl.org/dc/terms/}modified']
W3CDTF = re.compile(r'[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z')


def relationships_of(archive, name, fixed, media_allowed):
    """Exact relationship set: each fixed type once with Pandoc's target, plus declared PNG media (document part only)."""
    root = ET.fromstring(archive.read(name))
    require(root.tag == '{' + PACKAGE_REL + '}Relationships' and not root.attrib, 'unexpected DOCX relationship part: ' + name)
    seen = {}; ids = set(); media = {}
    for rel in root:
        require(rel.tag == '{' + PACKAGE_REL + '}Relationship' and len(rel) == 0 and set(rel.attrib) == {'Id', 'Type', 'Target'},
                'unexpected DOCX relationship element in ' + name)
        require(rel.get('Id') not in ids, 'duplicate DOCX relationship id in ' + name); ids.add(rel.get('Id'))
        kind, target = rel.get('Type'), rel.get('Target')
        if kind in fixed:
            require(kind not in seen and target == fixed[kind], 'DOCX relationship type or target differs in %s: %s -> %s' % (name, kind.rsplit('/', 1)[-1], target))
            seen[kind] = target
        else:
            require(media_allowed and kind == REL + 'image' and MEDIA.fullmatch(target or '') is not None and target not in media.values(),
                    'unexpected DOCX relationship in %s: %s -> %s' % (name, (kind or '').rsplit('/', 1)[-1], target))
            media[rel.get('Id')] = target
    require(set(seen) == set(fixed), 'DOCX relationship set differs in ' + name)
    return media


def docx_package(archive, infos, names, title, metadata=None):
    """Closed package: returns {relationship id: media target} after membership, relationship and content-type checks."""
    for info in infos:
        require(not info.flag_bits & 1 and info.compress_type in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED), 'DOCX encrypted or unsupported compression: ' + info.filename)
    root_rels = relationships_of(archive, '_rels/.rels', ROOT_RELATIONSHIPS, False); require(not root_rels, 'DOCX package root media unsupported')
    media = relationships_of(archive, 'word/_rels/document.xml.rels', DOCUMENT_RELATIONSHIPS, True)
    required = {'[Content_Types].xml', '_rels/.rels', 'word/document.xml', 'word/_rels/document.xml.rels', 'docProps/core.xml', *DOCX_FIXED_PARTS,
                *('word/' + target for target in media.values())}
    require(set(names) == required, 'unexpected DOCX package member: ' + ', '.join(sorted(set(names) ^ required)))
    for name, digest in DOCX_FIXED_PARTS.items():
        require(hashlib.sha256(archive.read(name)).hexdigest() == digest,
                'DOCX %s differs from qualified Pandoc 3.12.1; review and requalify the native writer parts' % name)
    types = ET.fromstring(archive.read('[Content_Types].xml'))
    require(types.tag == '{' + CONTENT_TYPES + '}Types' and not types.attrib, 'unexpected DOCX content types root')
    defaults = {}; overrides = {}
    for entry in types:
        if entry.tag == '{' + CONTENT_TYPES + '}Default' and set(entry.attrib) == {'Extension', 'ContentType'} and len(entry) == 0:
            require(entry.get('Extension') not in defaults, 'duplicate DOCX default content type'); defaults[entry.get('Extension')] = entry.get('ContentType')
        elif entry.tag == '{' + CONTENT_TYPES + '}Override' and set(entry.attrib) == {'PartName', 'ContentType'} and len(entry) == 0:
            require(entry.get('PartName') not in overrides, 'duplicate DOCX content type override'); overrides[entry.get('PartName')] = entry.get('ContentType')
        else: fail('VERIFICATION_FAILED', 'unexpected DOCX content type entry')
    require(defaults == CONTENT_DEFAULTS, 'DOCX default content types differ')
    require(overrides == {**CONTENT_OVERRIDES, **{'/word/' + t: 'image/png' for t in media.values()}}, 'DOCX content type overrides differ')
    core = ET.fromstring(archive.read('docProps/core.xml'))
    authors, description = declared(metadata)
    # Pandoc joins the creators with '; ' (an author never contains a semicolon, so the list is recoverable) and writes the description after them.
    tags = [*CORE_TAGS[:2], *([DESCRIPTION_TAG] if description is not None else []), *CORE_TAGS[2:]]
    shift = len(tags) - len(CORE_TAGS)
    require(core.tag == '{http://schemas.openxmlformats.org/package/2006/metadata/core-properties}coreProperties'
            and [c.tag for c in core] == tags and (core[0].text or '') == title and (core[1].text or '') == '; '.join(authors)
            and (description is None or (core[2].text or '') == description) and not (core[2 + shift].text or '')
            and all(len(c) == 0 for c in core) and all(W3CDTF.fullmatch(c.text or '') for c in core[3 + shift:]), 'DOCX core properties differ from the report title and declared metadata')
    return media


def w(name): return '{'+NS['w']+'}'+name


def docx_paragraph(paragraph):
    """Reviewed writer paragraph grammar: style, bookmarks and runs of plain text; no run properties, no drawings."""
    for child in paragraph:
        require(child.tag in (w('pPr'),w('r'),w('bookmarkStart'),w('bookmarkEnd')),'unexpected DOCX paragraph content: '+child.tag.rsplit('}',1)[-1])
        if child.tag==w('pPr'): require([c.tag for c in child] in ([],[w('pStyle')]),'unexpected DOCX paragraph properties')
        if child.tag==w('r'):
            # Pandoc marks East Asian (Han and punctuation) runs with a font hint only; no other run property is reviewed.
            hint=[c for c in child if c.tag==w('rPr')]
            require(len(hint)<=1 and all(len(c)==1 and c[0].tag==w('rFonts') and set(c[0].attrib)=={w('hint')} and c[0].get(w('hint'))=='eastAsia' for c in hint),
                    'unexpected DOCX run properties')
            require(all(c.tag in (w('rPr'),w('t')) for c in child),'unexpected DOCX run content (drawings are allowed only in declared image paragraphs)')
            for t in child.findall('w:t',NS):
                require(set(t.attrib)<={'{http://www.w3.org/XML/1998/namespace}space'} and len(t)==0,'unexpected DOCX text attributes')


IMAGE_STYLES = ('FirstParagraph', 'BodyText')
INLINE_TAGS = ['{%s}%s' % (NS['wp'], n) for n in ('extent', 'effectExtent', 'docPr')] + ['{%s}graphic' % NS['a']]


def docx_image_paragraph(paragraph):
    """Declared image paragraph: body style, one run holding exactly one inline picture with one plain blip."""
    parts = list(paragraph)
    require(len(parts) == 2 and parts[0].tag == w('pPr') and [c.tag for c in parts[0]] == [w('pStyle')] and parts[1].tag == w('r'), 'DOCX image paragraph structure differs')
    require([c.tag for c in parts[1]] == [w('drawing')], 'DOCX image run must hold exactly one drawing')
    drawing = parts[1][0]
    require([c.tag for c in drawing] == ['{%s}inline' % NS['wp']], 'DOCX image must be one inline drawing (anchored or floating shapes unsupported)')
    inline = drawing[0]
    require([c.tag for c in inline] == INLINE_TAGS, 'DOCX inline drawing structure differs')
    require(not inline.attrib and set(inline[0].attrib)=={'cx','cy'} and inline[1].attrib=={'b':'0','l':'0','r':'0','t':'0'},'unexpected DOCX inline layout properties')
    props=inline[2]
    require({'descr','id','name'}<=set(props.attrib)<={'descr','title','id','name'} and props.get('title','')=='' and props.get('name')=='Picture'
            and re.fullmatch(r'[1-9][0-9]*',props.get('id','')) and len(props)==0,'unexpected DOCX image properties')
    pictures = list(inline.iter('{http://schemas.openxmlformats.org/drawingml/2006/picture}pic'))
    blips = list(inline.iter('{%s}blip' % NS['a']))
    require(len(pictures) == 1 and len(blips) == 1 and len(blips[0]) == 0 and set(blips[0].attrib) == {'{%s}embed' % NS['r']},
            'DOCX image must be exactly one picture with one plain blip')
    require(len(list(inline.iter('{%s}graphicData' % NS['a']))) == 1, 'DOCX inline drawing holds more than one graphic')
    picture_namespace='http://schemas.openxmlformats.org/drawingml/2006/picture'
    fills=list(pictures[0].iter('{'+picture_namespace+'}blipFill'))
    require(len(fills)==1 and not fills[0].attrib and [c.tag for c in fills[0]]==['{'+NS['a']+'}blip','{'+NS['a']+'}stretch'], 'unexpected DOCX image fill or crop')
    stretch=fills[0][1]
    require(not stretch.attrib and len(stretch)==1 and stretch[0].tag=='{'+NS['a']+'}fillRect' and not stretch[0].attrib and len(stretch[0])==0,'unexpected DOCX image fill or crop')


def docx_table(table):
    """One flagged header row, unflagged body rows; each cell holds exactly one plain-text paragraph."""
    parts=[c for c in table if c.tag!=w('tr')]
    require([c.tag for c in parts]==[w('tblPr'),w('tblGrid')],'unexpected DOCX table structure')
    expected_properties={w('tblStyle'):{w('val'):'Table'},w('tblW'):{w('type'):'auto',w('w'):'0'},
        w('tblLook'):{w(k):v for k,v in {'firstRow':'1','lastRow':'0','firstColumn':'0','lastColumn':'0','noHBand':'0','noVBand':'0','val':'0020'}.items()}}
    require(not parts[0].attrib and len({c.tag for c in parts[0]})==len(parts[0]) and all(c.tag in expected_properties and c.attrib==expected_properties[c.tag] and len(c)==0 for c in parts[0]),'unexpected DOCX table layout properties')
    columns=len(parts[1]); rows=table.findall('w:tr',NS); require(len(rows)>=2 and len(rows)+2==len(table),'DOCX table rows differ')
    result=[]
    for index,row in enumerate(rows):
        flags=[c for c in row if c.tag==w('trPr')]
        require(len(flags)<=1 and all(c.tag in (w('trPr'),w('tc')) for c in row) and (not flags or row[0] is flags[0]),'unexpected DOCX row structure')
        header=bool(flags) and [c.tag for c in flags[0]]==[w('tblHeader')] and flags[0][0].get(w('val'),'on') in ('on','1','true')
        require(header==(index==0) and (index==0 or not flags),'DOCX table header row flag differs')
        cells=row.findall('w:tc',NS); require(len(cells)==columns,'DOCX table cell count differs from grid')
        values=[]
        for cell in cells:
            require([c.tag for c in cell]==[w('tcPr'),w('p')] and len(cell[0])==0,'DOCX table cell must hold exactly one paragraph')
            docx_paragraph(cell[1]); values.append(''.join(t.text or '' for t in cell[1].findall('.//w:t',NS)))
        result.append(values)
    return result


def docx_report(data,title,model,metadata=None):
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            infos=archive.infolist(); names=[i.filename for i in infos]
            require(len(names)==len(set(names)) and len(names)<=128 and sum(i.file_size for i in infos)<=32*1024*1024,'DOCX archive resource/membership limit')
            require(all(not PurePosixPath(n).is_absolute() and '..' not in PurePosixPath(n).parts for n in names),'unsafe DOCX archive member')
            media=docx_package(archive,infos,names,title,metadata)
            document=ET.fromstring(archive.read('word/document.xml'))
            require(document.find('.//w:sectPr/w:headerReference',NS) is None and document.find('.//w:sectPr/w:footerReference',NS) is None,'DOCX header/footer reference unsupported')
            sections=document.findall('.//w:sectPr',NS)
            for section in sections:
                require(not section.attrib and (len(section)==0 or (len(section)==1 and section[0].tag==w('footnotePr') and not section[0].attrib and len(section[0])==1
                    and section[0][0].tag==w('numRestart') and section[0][0].attrib=={w('val'):'eachSect'} and len(section[0][0])==0)),'unexpected DOCX section layout properties')
            for local in ('tab','br','cr','fldChar','instrText','hyperlink','object','altChunk','del','ins','vanish','pict','anchor'):
                require(document.find('.//w:'+local,NS) is None and document.find('.//wp:'+local,NS) is None,'unsupported DOCX inline/control: '+local)
            # The only relationship reference in the body is each declared picture's blip embed.
            references=[(e.tag,k) for e in document.iter() for k in e.attrib if k.startswith('{'+NS['r']+'}')]
            require(all(tag=='{'+NS['a']+'}blip' and k=='{'+NS['r']+'}embed' for tag,k in references),'unexpected DOCX relationship reference in the document body')
            result=[]; titles=[]; used_media=[]; authors=[]
            def text(node): return ''.join(t.text or '' for t in node.findall('.//w:t',NS))
            body=document.find('w:body',NS); require(body is not None,'DOCX body missing')
            for node in body:
                if node.tag=='{'+NS['w']+'}sectPr': continue
                if node.tag=='{'+NS['w']+'}tbl':
                    result.append({'kind':'table','rows':docx_table(node)}); continue
                require(node.tag=='{'+NS['w']+'}p','unexpected DOCX block')
                style=node.find('w:pPr/w:pStyle',NS); name=style.get('{'+NS['w']+'}val') if style is not None else ''
                if node.find('.//w:drawing',NS) is not None:
                    original=model[len(result)] if len(result)<len(model) else None
                    require(name in IMAGE_STYLES and original is not None and original['kind']=='image','DOCX drawing outside a declared image paragraph')
                    docx_image_paragraph(node)
                    rel=node.find('.//a:blip',NS).attrib['{'+NS['r']+'}embed']
                    require(rel in media,'invalid DOCX media relationship')
                    target=str(PurePosixPath('word')/media[rel]); used_media.append(target)
                    image=archive.read(target); props=node.findall('.//wp:docPr',NS); extent=node.findall('.//wp:extent',NS)
                    require(len(props)==len(extent)==1,'DOCX image geometry/alt missing')
                    require(abs(int(extent[0].attrib['cx'])/36000-original['widthMm'])<=2/36000,'DOCX image width differs beyond two EMU')
                    from .adaptor import png
                    dimensions=png(image,'DOCX media'); height=original['widthMm']*dimensions['height']/dimensions['width']
                    require(abs(int(extent[0].attrib['cy'])/36000-height)<=2/36000,'DOCX image aspect ratio differs beyond two EMU')
                    result.append({'kind':'image','alt':props[0].get('descr'),'sha256':hashlib.sha256(image).hexdigest(),
                                   'widthMm':original['widthMm']}); continue
                docx_paragraph(node)
                if name=='Title': titles.append(text(node)); continue
                # Declared authors are the Author-style title-block paragraphs between the title and the first section; anywhere else the style fails the model below.
                if name=='Author' and titles and not result: authors.append(text(node)); continue
                if name.startswith('Heading'):
                    result.append({'kind':'heading','level':int(name[7:]),'text':text(node)})
                else:
                    # Pandoc inserts an empty paragraph after a table at document end.
                    if not text(node) and node is list(body)[-2]: continue
                    result.append({'kind':'paragraph','text':text(node)})
            images=sum(b['kind']=='image' for b in model)
            require(len(document.findall('.//w:drawing',NS))==len(document.findall('.//a:blip',NS))==len(used_media)==images,'DOCX picture count differs from the declared images')
            # Pandoc stores byte-identical images once, so several declared pictures may share one media relationship.
            require(set(used_media)=={'word/'+t for t in media.values()},'DOCX undeclared media membership differs')
            require(titles==[title],'DOCX visible title differs'); require(authors==declared(metadata)[0],'DOCX visible author list differs from the declared authors'); require(result==model,'DOCX ordered heading/text/table/image semantics differ')
    except (zipfile.BadZipFile,zipfile.LargeZipFile,ET.ParseError,KeyError,ValueError,OverflowError,EOFError,RuntimeError,NotImplementedError,zlib.error) as error:
        fail('VERIFICATION_FAILED','invalid DOCX package: '+type(error).__name__+': '+str(error)[:200])


def inline_text(items):
    result=''
    for item in items:
        if item['t']=='Str': result+=item['c']
        elif item['t'] in ('Space','SoftBreak'): result+=' '
        elif item['t']=='Span': result+=inline_text(item['c'][1])
        else: fail('VERIFICATION_FAILED','unexpected native readback inline: '+item['t'])
    return result


def meta_authors(node):
    """Author strings of a Pandoc readback `author`: one author reads back as a single MetaInlines, several as a MetaList of them."""
    require(isinstance(node,dict) and set(node)=={'t','c'},'native readback author differs')
    if node['t']=='MetaInlines': return [inline_text(node['c'])]
    require(node['t']=='MetaList' and isinstance(node['c'],list) and all(isinstance(i,dict) and i.get('t')=='MetaInlines' for i in node['c']),'native readback author list differs')
    return [inline_text(i['c']) for i in node['c']]


def ast_report(value,directory,title,model,metadata=None):
    authors,_=declared(metadata)
    # The DOCX reader reports the title and the Author-style paragraphs; it has no description, so that is checked in the package core properties only.
    require(set(value['meta'])=={'title',*(['author'] if authors else [])},'DOCX native readback metadata differs from the declared metadata')
    if authors: require(meta_authors(value['meta']['author'])==authors,'DOCX native readback authors differ from the declared authors')
    meta=value['meta'].get('title',{})
    require(meta.get('t')=='MetaInlines' and inline_text(meta['c'])==title,'DOCX native readback title differs')
    result=[]
    for block in value['blocks']:
        kind=block['t']; content=block.get('c')
        if kind=='Header': result.append({'kind':'heading','level':content[0],'text':inline_text(content[2])})
        elif kind in ('Para','Plain'):
            if len(content)==1 and content[0]['t']=='Image':
                image=content[0]['c']; path=Path(image[2][0]); require(not path.is_absolute() and '..' not in path.parts and path.parts[:2]==('reopened','media'),'native extracted media path differs')
                require(not any((directory/Path(*path.parts[:n])).is_symlink() for n in range(1,len(path.parts)+1)),'native media symlink unsupported')
                from .adaptor import bounded
                original=next((b for b in model[len(result):len(result)+1] if b['kind']=='image'),None)
                require(original is not None,'native image order differs')
                attributes=dict(image[0][2]); width=attributes.get('width','')
                # The DOCX reader reports physical width in inches.
                require(width.endswith('in') and abs(float(width[:-2])*25.4-original['widthMm'])<0.001,'native readback image width differs')
                result.append({'kind':'image','alt':inline_text(image[1]),'sha256':hashlib.sha256(bounded(directory/path)).hexdigest(),
                               'widthMm':original['widthMm']})
            else: result.append({'kind':'paragraph','text':inline_text(content)})
        elif kind=='Table':
            require(len(content[3][1])==1 and len(content[4])==1 and content[4][0][1]==0 and content[4][0][2]==[] and content[5][1]==[]
                    and content[4][0][3],'native table must be one header row, one body group of data rows and no footer')
            rows=[*content[3][1],*content[4][0][3]]
            def cell_text(cell):
                require(cell[2:4]==[1,1] and len(cell[4])==1 and cell[4][0]['t'] in ('Plain','Para'),'native table spans/cell structure differs')
                return inline_text(cell[4][0]['c'])
            result.append({'kind':'table','rows':[[cell_text(c) for c in row[1]] for row in rows]})
        else: fail('VERIFICATION_FAILED','unexpected native readback block: '+kind)
    require(result==model,'fresh native DOCX readback ordered semantics differ')
