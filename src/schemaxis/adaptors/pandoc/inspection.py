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

from schemaxis.errors import fail

# Reviewed native Pandoc 3.12.1 default HTML stylesheet (2701 UTF-8 bytes).
# An upstream style change requires review and fresh native qualification.
# Keep this in trusted code: an editable run receipt cannot approve new CSS.
QUALIFIED_STYLESHEET_SHA256 = '9466a348764bb1184fd84927af08d92a0b7a72627a5a27f374c1cdb7c34d5714'


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
        if tag not in ('img','meta','link','br','hr','input','source','wbr','area','base','col','embed','param','track'): self.stack.append(node)
    def handle_startendtag(self, tag, attrs):
        node=Node(tag,attrs); self.stack[-1].children.append(node)
    def handle_endtag(self, tag):
        if len(self.stack)>1:
            require(self.stack[-1].tag==tag,'malformed native HTML nesting'); self.stack.pop()
    def handle_data(self,data): self.stack[-1].children.append(data)


def html_report(source,title,model):
    parser=HTML(); parser.feed(source); root=parser.root
    require([n.text() for n in root.all('title')]==[title], 'HTML browser title differs')
    require(not any(list(root.all(tag)) for tag in ('script','iframe','link','base','object','embed')),'HTML contains active content or external resources')
    for node in root.all('meta'):
        require(set(node.attrs)<= {'charset','name','content'} and node.attrs.get('name','') in ('','generator','viewport'),'HTML unexpected metadata or refresh')
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
    def grammar(node):
        require(node.tag in allowed and set(node.attrs)<=allowed[node.tag],'unexpected HTML content/attribute: '+node.tag)
        for child in node.children:
            if isinstance(child,Node): grammar(child)
    grammar(body[0])
    def visit(node):
        if node.tag=='header':
            titles.extend(n.text() for n in node.all('h1')); return
        if node.tag in ('h1','h2','h3'):
            result.append({'kind':'heading','level':int(node.tag[1]),'text':' '.join(node.text().split())}); return
        if node.tag=='table':
            result.append({'kind':'table','rows':[[cell.text() for cell in row.children if isinstance(cell,Node) and cell.tag in ('td','th')] for row in node.all('tr')]}); return
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
            else: result.append({'kind':'paragraph','text':' '.join(node.text().split())})
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


def docx_report(data,title,model):
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            infos=archive.infolist(); names=[i.filename for i in infos]
            require(len(names)==len(set(names)) and len(names)<=128 and sum(i.file_size for i in infos)<=32*1024*1024,'DOCX archive resource/membership limit')
            require(all(not PurePosixPath(n).is_absolute() and '..' not in PurePosixPath(n).parts for n in names),'unsafe DOCX archive member')
            document=ET.fromstring(archive.read('word/document.xml')); rels=ET.fromstring(archive.read('word/_rels/document.xml.rels'))
            relationships={r.attrib['Id']:r.attrib for r in rels}
            require(all(r.get('TargetMode')!='External' for r in relationships.values()),'DOCX external relationship unsupported')
            for local in ('tab','br','cr','fldChar','instrText','hyperlink','object','altChunk','del','ins','vanish'):
                require(document.find('.//w:'+local,NS) is None,'unsupported DOCX inline/control: '+local)
            result=[]; titles=[]; used_media=set()
            def text(node): return ''.join(t.text or '' for t in node.findall('.//w:t',NS))
            body=document.find('w:body',NS); require(body is not None,'DOCX body missing')
            for node in body:
                if node.tag=='{'+NS['w']+'}sectPr': continue
                if node.tag=='{'+NS['w']+'}tbl':
                    result.append({'kind':'table','rows':[[text(cell) for cell in row.findall('w:tc',NS)] for row in node.findall('w:tr',NS)]}); continue
                require(node.tag=='{'+NS['w']+'}p','unexpected DOCX block')
                style=node.find('w:pPr/w:pStyle',NS); name=style.get('{'+NS['w']+'}val') if style is not None else ''
                if name=='Title': titles.append(text(node)); continue
                images=node.findall('.//a:blip',NS)
                if images:
                    require(len(images)==1 and not text(node),'DOCX image paragraph differs')
                    rel=relationships[images[0].attrib['{'+NS['r']+'}embed']]
                    target=PurePosixPath('word')/rel['Target']; require('..' not in target.parts and rel['Type'].endswith('/image'),'invalid DOCX media relationship')
                    used_media.add(str(target)); image=archive.read(str(target)); props=node.findall('.//wp:docPr',NS); extent=node.findall('.//wp:extent',NS)
                    require(len(props)==len(extent)==1,'DOCX image geometry/alt missing')
                    original=model[len(result)]
                    require(original['kind']=='image' and abs(int(extent[0].attrib['cx'])/36000-original['widthMm'])<=2/36000,'DOCX image width differs beyond two EMU')
                    from .adaptor import png
                    dimensions=png(image,'DOCX media'); height=original['widthMm']*dimensions['height']/dimensions['width']
                    require(abs(int(extent[0].attrib['cy'])/36000-height)<=2/36000,'DOCX image aspect ratio differs beyond two EMU')
                    result.append({'kind':'image','alt':props[0].get('descr'),'sha256':hashlib.sha256(image).hexdigest(),
                                   'widthMm':original['widthMm']}); continue
                if name.startswith('Heading'):
                    result.append({'kind':'heading','level':int(name[7:]),'text':text(node)})
                else:
                    # Pandoc inserts an empty paragraph after a table at document end.
                    if not text(node) and node is list(body)[-2]: continue
                    result.append({'kind':'paragraph','text':text(node)})
            require({n for n in names if n.startswith('word/media/')}==used_media,'DOCX undeclared media membership differs')
            require(titles==[title],'DOCX visible title differs'); require(result==model,'DOCX ordered heading/text/table/image semantics differ')
    except (zipfile.BadZipFile,ET.ParseError,KeyError,ValueError) as error:
        fail('VERIFICATION_FAILED','invalid DOCX package: '+str(error))


def inline_text(items):
    result=''
    for item in items:
        if item['t']=='Str': result+=item['c']
        elif item['t'] in ('Space','SoftBreak'): result+=' '
        elif item['t']=='Span': result+=inline_text(item['c'][1])
        else: fail('VERIFICATION_FAILED','unexpected native readback inline: '+item['t'])
    return result


def ast_report(value,directory,title,model):
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
            rows=[*content[3][1]]
            for body in content[4]: rows.extend(body[2]); rows.extend(body[3])
            rows.extend(content[5][1])
            def cell_text(cell):
                require(cell[2:4]==[1,1] and len(cell[4])==1 and cell[4][0]['t'] in ('Plain','Para'),'native table spans/cell structure differs')
                return inline_text(cell[4][0]['c'])
            result.append({'kind':'table','rows':[[cell_text(c) for c in row[1]] for row in rows]})
        else: fail('VERIFICATION_FAILED','unexpected native readback block: '+kind)
    require(result==model,'fresh native DOCX readback ordered semantics differ')
