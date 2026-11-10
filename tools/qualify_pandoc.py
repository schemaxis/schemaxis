#!/usr/bin/env python3
# Copyright (C) 2026 David L F Gaden
"""Bounded Pandoc report qualification, hostile evidence and workflow reuse."""
import argparse
import copy
import hashlib
import html
import io
import json
from pathlib import Path
import re
import shutil
import xml.etree.ElementTree as ET
import zipfile

from schemaxis.adaptor_conformance import qualify, register
from schemaxis.adaptor_delivery import case_document, route_materials
from schemaxis.adaptors.pandoc import adaptor
from schemaxis.core import timed_text
from schemaxis.artifacts import atomic_json
from schemaxis.core.faults import SchemaxisError
from schemaxis import workflow

ROOT=Path(__file__).resolve().parents[1]


def refused(action,code='VERIFICATION_FAILED',reason=None):
    try: action()
    except SchemaxisError as error:
        assert error.fault.code==code,error.fault.to_dict()
        # A probe that names its intended reason must be refused for that reason, not for an incidental one.
        assert reason is None or reason in error.fault.message,(reason,error.fault.to_dict())
        return error.fault.to_dict()
    raise AssertionError('invalid evidence accepted')


def refresh(directory):
    """Refresh ordinary hashes; semantic checks must still reject forged content."""
    receipt=adaptor.read(directory,'verification.json')
    receipt['artifacts']=adaptor.artifacts(directory)
    receipt['evidence']={name:adaptor.digest(directory,name) for name in receipt['evidence']}
    atomic_json(directory/'verification.json',receipt)
    # Common publication metadata is independent of native semantics.
    from schemaxis.publication_metadata import finalise
    finalise(directory)


def negative(directory,report):
    saved={p:p.read_bytes() for p in directory.rglob('*') if p.is_file()}
    def restore():
        for p in sorted((p for p in directory.rglob('*') if p not in saved and not p.is_dir()),key=str,reverse=True): p.unlink()
        for p,data in saved.items(): p.write_bytes(data)
    for name in ('report.html','reopened.json','report.docx','report-input.json'):
        try:
            path=directory/name
            if name=='report.docx':
                buffer=io.BytesIO()
                with zipfile.ZipFile(path) as old,zipfile.ZipFile(buffer,'w') as new:
                    for item in old.infolist():
                        data=old.read(item.filename)
                        if item.filename=='word/document.xml':
                            assert b'12.0' in data;data=data.replace(b'12.0',b'99.0',1)
                        new.writestr(item,data)
                path.write_bytes(buffer.getvalue())
                # Refresh binding to force independent OOXML acceptance, beyond stale readback guard.
                inputs=adaptor.read(directory,'reopen-inputs.json');inputs[str(directory/'report.docx')]=adaptor.digest(directory,'report.docx');atomic_json(directory/'reopen-inputs.json',inputs)
            else:
                data=path.read_bytes();assert b'12.0' in data;path.write_bytes(data.replace(b'12.0',b'99.0',1))
            refresh(directory)
            report[name+'WithRefreshedHashes']=refused(lambda:adaptor.verify(directory))['code']
        finally: restore()
    try:
        path=directory/'report.html';path.write_text(path.read_text().replace('<p>Measured','<p hidden=\"hidden\">Measured',1));refresh(directory)
        report['hiddenHTMLWithRefreshedHashes']=refused(lambda:adaptor.verify(directory))['code']
    finally:restore()
    for label,old,new in [
        ('eventAttribute','<html xmlns=', '<html onload="alert(1)" xmlns='),
        ('metaRefresh','<meta charset="utf-8" />','<meta http-equiv="refresh" content="0;url=https://invalid.example" />'),
        ('externalCSS','<style>','<style>@import "https://invalid.example/style.css";'),
        ('hiddenBodyStylesheet','</style>','body { display:none }</style>'),
        ('transparentParagraphStylesheet','</style>','p { opacity:0 }</style>'),
        ('externalMedia','data:image/png;base64,','https://invalid.example/')]:
        try:
            path=directory/'report.html';source=path.read_text();assert old in source;path.write_text(source.replace(old,new,1));refresh(directory)
            report[label+'WithRefreshedHashes']=refused(lambda:adaptor.verify(directory))['code']
        finally:restore()
    def docx_member(label,change):
        try:
            path=directory/'report.docx';buffer=io.BytesIO()
            with zipfile.ZipFile(path) as old,zipfile.ZipFile(buffer,'w') as new: change(old,new)
            path.write_bytes(buffer.getvalue())
            inputs=adaptor.read(directory,'reopen-inputs.json');inputs[str(path)]=adaptor.digest(directory,'report.docx');atomic_json(directory/'reopen-inputs.json',inputs)
            refresh(directory);report[label+'WithRefreshedHashes']=refused(lambda:adaptor.verify(directory))['code']
        finally:restore()
    def add_member(name,data):
        def change(old,new):
            for item in old.infolist(): new.writestr(item,old.read(item.filename))
            new.writestr(name,data)
        return change
    docx_member('docxMacroMember',add_member('word/vbaProject.bin',b'MZ'))
    docx_member('docxHiddenHeaderPart',add_member('word/header1.xml',b'<w:hdr xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:p><w:r><w:t>FAKE</w:t></w:r></w:p></w:hdr>'))
    for label,old,new in [('htmlTextAfterBody','</body>','</body>FAKE VISIBLE CONCLUSION'),('htmlElementAfterBody','</body>','</body><p>FAKE</p>'),('htmlComment','<body>','<body><!-- hidden -->')]:
        try:
            path=directory/'report.html';source=path.read_text();assert old in source;path.write_text(source.replace(old,new,1));refresh(directory)
            report[label+'WithRefreshedHashes']=refused(lambda:adaptor.verify(directory))['code']
        finally:restore()
    for label,action in [('undeclaredFile',lambda:(directory/'report.pdf').write_bytes(b'%PDF fake')),
                         ('extraExtractedMedia',lambda:((directory/'reopened/media').mkdir(parents=True,exist_ok=True),(directory/'reopened/media/extra.png').write_bytes(b'x'))),
                         ('deeplyNestedReadback',lambda:(directory/'reopened.json').write_text('['*200000+']'*200000)),
                         ('duplicateKeyAST',lambda:(directory/'report-input.json').write_text('{"meta":{},"meta":{},"blocks":[]}'))]:
        try:
            action();refresh(directory);report[label+'WithRefreshedHashes']=refused(lambda:adaptor.verify(directory))['code']
        finally:restore()
    try:
        # Preserve ordinary receipts while changing the retained native input.
        path=directory/'report.docx';path.write_bytes(path.read_bytes()+b'changed archive trailer');refresh(directory)
        error=refused(lambda:adaptor.verify(directory));assert 'consumed different' in error['message'];report['staleNativeReadbackBinding']=error['code']
    finally:restore()
    assert adaptor.verify(directory)['verified']


# Independent literal expectations for the transcript case. They are written out here, not derived from the
# example file or from adaptor.expected(), so a shared mistake in either cannot make both sides agree.
TRANSCRIPT_HEADER=['Start (ms)','End (ms)','Text']
TRANSCRIPT_ROWS=[['0','1250','Good morning, and thank you for joining us.'],
                 ['1250','3000','Today we compare a < b & c > d in plain text.'],
                 ['3000','4875','Bonjour, ça va ? 你好。']]
W='{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'


def literal_html_table(source):
    """Rows keyed by cell element, so a header demoted to a body row is a different answer."""
    head=re.search(r'<thead>(.*?)</thead>\s*<tbody>(.*?)</tbody>',source,re.S);assert head,'HTML table needs thead then tbody'
    cells=lambda text,tag:[[html.unescape(c) for c in re.findall('<%s>(.*?)</%s>'%(tag,tag),row,re.S)] for row in re.findall('<tr>(.*?)</tr>',text,re.S)]
    return cells(head.group(1),'th'),cells(head.group(2),'td')


def literal_docx_table(path):
    with zipfile.ZipFile(path) as archive: document=ET.fromstring(archive.read('word/document.xml'))
    rows=document.findall('.//'+W+'tbl/'+W+'tr')
    flagged=[row.find(W+'trPr/'+W+'tblHeader') is not None for row in rows]
    paragraphs=[[len(cell.findall(W+'p')) for cell in row.findall(W+'tc')] for row in rows]
    return flagged,paragraphs,[[''.join(t.text or '' for t in cell.iter(W+'t')) for cell in row.findall(W+'tc')] for row in rows]


def literal_readback_table(path):
    def text(items): return ''.join(i['c'] if i['t']=='Str' else ' ' for i in items)
    table=next(b for b in json.loads(path.read_text())['blocks'] if b['t']=='Table')['c']
    row=lambda r:[text(c[4][0]['c']) for c in r[1]]
    return [row(r) for r in table[3][1]],[row(r) for b in table[4] for r in b[3]],len(table[4]),len(table[5][1])


def transcript_literals(directory,report):
    """Check retained transcript publications against literal expectations, not the adaptor's own model."""
    header,body=literal_html_table((directory/'report.html').read_text(encoding='utf-8'))
    assert header==[TRANSCRIPT_HEADER] and body==TRANSCRIPT_ROWS,(header,body)
    flagged,paragraphs,rows=literal_docx_table(directory/'report.docx')
    assert flagged==[True,False,False,False] and rows==[TRANSCRIPT_HEADER,*TRANSCRIPT_ROWS] and all(set(p)=={1} for p in paragraphs),(flagged,rows)
    head,tail,bodies,footers=literal_readback_table(directory/'reopened.json')
    assert head==[TRANSCRIPT_HEADER] and tail==TRANSCRIPT_ROWS and bodies==1 and footers==0,(head,tail)
    # Times stay literal digit strings labelled in milliseconds, in order, never reformatted as clock times.
    assert TRANSCRIPT_HEADER[:2]==['Start (ms)','End (ms)'] and all(r[0].isdigit() and r[1].isdigit() and int(r[0])<=int(r[1]) for r in TRANSCRIPT_ROWS)
    assert all(int(a[1])==int(b[0]) for a,b in zip(TRANSCRIPT_ROWS,TRANSCRIPT_ROWS[1:]))
    report['literalTranscript']={'rows':len(TRANSCRIPT_ROWS),'html':True,'docx':True,'readback':True}


def transcript_negative(directory,report):
    """Refreshed-hash forgeries of transcript semantics must fail independent verification."""
    saved={p:p.read_bytes() for p in directory.rglob('*') if p.is_file()}
    def restore():
        for p in sorted((p for p in directory.rglob('*') if p not in saved and not p.is_dir()),key=str,reverse=True): p.unlink()
        for p,data in saved.items(): p.write_bytes(data)
    def html_edit(label,old,new):
        try:
            path=directory/'report.html';source=path.read_text(encoding='utf-8');assert old in source,label;path.write_text(source.replace(old,new,1),encoding='utf-8');refresh(directory)
            report[label]=refused(lambda:adaptor.verify(directory))['code']
        finally:restore()
    def docx_edit(label,part,old,new,reason=None):
        try:
            path=directory/'report.docx';buffer=io.BytesIO()
            with zipfile.ZipFile(path) as source,zipfile.ZipFile(buffer,'w') as target:
                for item in source.infolist():
                    data=source.read(item.filename)
                    if item.filename==part: assert old in data,label;data=data.replace(old,new,1)
                    target.writestr(item,data)
            path.write_bytes(buffer.getvalue())
            inputs=adaptor.read(directory,'reopen-inputs.json');inputs[str(path)]=adaptor.digest(directory,'report.docx');atomic_json(directory/'reopen-inputs.json',inputs)
            refresh(directory);report[label]=refused(lambda:adaptor.verify(directory),reason=reason)['code']
        finally:restore()
    html_edit('transcriptHTMLTimestamp','<td>1250</td>','<td>1260</td>')
    html_edit('transcriptHTMLUnitLabel','Start (ms)','Start (s)')
    html_edit('transcriptHTMLHeaderCells','<th>End (ms)</th>','<td>End (ms)</td>')
    html_edit('transcriptHTMLDoubledSpace','Good morning,','Good  morning,')
    html_edit('transcriptHTMLZeroWidth','Good morning','Good\u200b morning')
    html_edit('transcriptHTMLNestedCellElement','<td>0</td>','<td>0<p>hidden</p></td>')
    docx_edit('transcriptDOCXTimestamp','word/document.xml',b'>1250<',b'>1260<')
    docx_edit('transcriptDOCXHeaderFlag','word/document.xml',b'<w:trPr><w:tblHeader w:val="on" /></w:trPr>',b'')
    docx_edit('transcriptDOCXSplitCell','word/document.xml',b'Good morning, and',b'Good morning,</w:t></w:r></w:p><w:p><w:r><w:t xml:space="preserve"> and')
    docx_edit('transcriptDOCXHiddenRun','word/document.xml',b'<w:r><w:t xml:space="preserve">Good',b'<w:r><w:rPr><w:vanish /></w:rPr><w:t xml:space="preserve">Good')
    docx_edit('transcriptDOCXStyleHidesText','word/styles.xml',b'<w:style w:type="paragraph" w:customStyle="1" w:styleId="Compact">',b'<w:style w:type="paragraph" w:customStyle="1" w:styleId="Compact"><w:rPr><w:vanish /></w:rPr>',
              'differs from qualified Pandoc')
    shape=OPAQUE_SHAPE.encode()
    docx_edit('transcriptDOCXAnchoredShapeInTimestampCell','word/document.xml',b'>1250</w:t></w:r>',b'>1250</w:t></w:r>'+shape,'unsupported DOCX inline/control: anchor')
    docx_edit('transcriptDOCXInlineShapeInTimestampCell','word/document.xml',b'>1250</w:t></w:r>',b'>1250</w:t></w:r>'+shape.replace(b'wp:anchor',b'wp:inline'),'unexpected DOCX run content')
    assert adaptor.verify(directory)['verified']


DRAWING='<w:r><w:drawing><wp:anchor><wp:extent cx="9999999" cy="9999999"/><a:graphic><a:graphicData uri="x"><a:blip r:embed="rId11"/></a:graphicData></a:graphic></wp:anchor></w:drawing></w:r>'
INLINE_DRAWING=DRAWING.replace('wp:anchor','wp:inline')
OPAQUE_SHAPE='<w:r><w:drawing><wp:anchor><wp:extent cx="9999999" cy="9999999"/><a:graphic><a:graphicData uri="x"/></a:graphic></wp:anchor></w:drawing></w:r>'


def package_negative(directory,report):
    """Refreshed-hash forgeries of DOCX package structure and picture placement; each names its intended reason."""
    saved={p:p.read_bytes() for p in directory.rglob('*') if p.is_file()}
    def restore():
        for p in sorted((p for p in directory.rglob('*') if p not in saved and not p.is_dir()),key=str,reverse=True): p.unlink()
        for p,data in saved.items(): p.write_bytes(data)
    def forge(label,mutate,reason):
        try:
            path=directory/'report.docx'
            with zipfile.ZipFile(path) as source: members={i.filename:source.read(i.filename) for i in source.infolist()}
            mutate(members)
            buffer=io.BytesIO()
            with zipfile.ZipFile(buffer,'w') as target:
                for name,data in members.items(): target.writestr(name,data)
            path.write_bytes(buffer.getvalue())
            inputs=adaptor.read(directory,'reopen-inputs.json');inputs[str(path)]=adaptor.digest(directory,'report.docx');atomic_json(directory/'reopen-inputs.json',inputs)
            refresh(directory);report[label]=refused(lambda:adaptor.verify(directory),reason=reason)['code']
        finally:restore()
    def replace(name,old,new):
        def change(members):
            assert old in members[name],(name,old);members[name]=members[name].replace(old,new,1)
        return change
    def chain(*changes):
        def change(members):
            for c in changes: c(members)
        return change
    def theme_two(members): members['word/theme/theme2.xml']=members['word/styles.xml'].replace(b'w:styleId="Compact">',b'w:styleId="Compact"><w:rPr><w:vanish /></w:rPr>',1)
    styles_type=b'<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml" />'
    forge('docxStylesRelationshipRepointed',chain(theme_two,
        replace('word/_rels/document.xml.rels',b'Target="styles.xml"',b'Target="theme/theme2.xml"'),
        replace('[Content_Types].xml',b'</Types>',b'<Override PartName="/word/theme/theme2.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml" /></Types>')),'relationship type or target differs')
    forge('docxOrphanThemePart',theme_two,'unexpected DOCX package member')
    forge('docxThemeFontEdited',replace('word/theme/theme1.xml',b'<a:minorFont>',b'<a:minorFont><a:latin typeface="Wingdings" />'),'word/theme/theme1.xml differs')
    forge('docxSettingsEdited',replace('word/settings.xml',b'<w:zoom w:percent="100" />',b'<w:zoom w:percent="1" />'),'word/settings.xml differs')
    forge('docxStylesContentTypeRetyped',replace('[Content_Types].xml',styles_type,styles_type.replace(b'wordprocessingml.styles+xml',b'wordprocessingml.template.main+xml')),'content type overrides differ')
    forge('docxImageRelationshipExternal',replace('word/_rels/document.xml.rels',b'Target="media/rId11.png"',b'Target="https://invalid.example/a.png" TargetMode="External"'),'unexpected DOCX relationship')
    forge('docxDuplicateStylesRelationship',replace('word/_rels/document.xml.rels',b'</Relationships>',b'<Relationship Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Id="rId99" Target="styles.xml" /></Relationships>'),'relationship type or target differs')
    cell=b'<w:t xml:space="preserve">14.0</w:t></w:r>'
    forge('docxAnchoredShapeInTableCell',replace('word/document.xml',cell,cell+OPAQUE_SHAPE.encode()),'unsupported DOCX inline/control: anchor')
    forge('docxInlineShapeInTableCell',replace('word/document.xml',cell,cell+OPAQUE_SHAPE.replace('wp:anchor','wp:inline').encode()),'unexpected DOCX run content')
    forge('docxImageReuseInTableCell',replace('word/document.xml',cell,cell+INLINE_DRAWING.encode()),'unexpected DOCX run content')
    sentence=b'a reading below 15 V.</w:t></w:r>'
    forge('docxDrawingInTextParagraph',replace('word/document.xml',sentence,sentence+INLINE_DRAWING.encode()),'drawing outside a declared image paragraph')
    forge('docxImageParagraphAnchored',lambda m:m.__setitem__('word/document.xml',m['word/document.xml'].replace(b'<wp:inline>',b'<wp:anchor>',1).replace(b'</wp:inline>',b'</wp:anchor>',1)),'unsupported DOCX inline/control: anchor')
    forge('docxTransparentBlip',replace('word/document.xml',b'<a:blip r:embed="rId11" />',b'<a:blip r:embed="rId11"><a:alphaModFix amt="0" /></a:blip>'),'one plain blip')
    forge('docxSecondPictureInImageParagraph',replace('word/document.xml',b'</w:drawing></w:r>',b'</w:drawing></w:r>'+INLINE_DRAWING.encode()),'image paragraph structure differs')
    assert adaptor.verify(directory)['verified']

    forge('docxFloatingTable',replace('word/document.xml',b'<w:tblPr>',b'<w:tblPr><w:tblpPr w:tblpX="-99999999"/>'),'table layout properties')
    forge('docxZeroPageSize',replace('word/document.xml',b'<w:sectPr>',b'<w:sectPr><w:pgSz w:w="0" w:h="0"/>'),'section layout properties')
    forge('docxHiddenPicture',replace('word/document.xml',b'<wp:docPr ',b'<wp:docPr hidden="1" '),'image properties')
    forge('docxCroppedPicture',replace('word/document.xml',b'<a:stretch>',b'<a:srcRect l="100000"/><a:stretch>'),'image fill or crop')


def multilingual_negative(directory,report):
    """Stripping a joiner or directional mark from any retained publication changes the text and must be refused."""
    saved={p:p.read_bytes() for p in directory.rglob('*') if p.is_file()}
    def restore():
        for p in sorted((p for p in directory.rglob('*') if p not in saved and not p.is_dir()),key=str,reverse=True): p.unlink()
        for p,data in saved.items(): p.write_bytes(data)
    try:
        path=directory/'report.html';source=path.read_text(encoding='utf-8');assert '\u200c' in source;path.write_text(source.replace('\u200c','',1),encoding='utf-8');refresh(directory)
        report['multilingualHTMLZwnjStripped']=refused(lambda:adaptor.verify(directory),reason='semantics differ')['code']
    finally:restore()
    try:
        path=directory/'report.docx';buffer=io.BytesIO()
        with zipfile.ZipFile(path) as source,zipfile.ZipFile(buffer,'w') as target:
            for item in source.infolist():
                data=source.read(item.filename)
                if item.filename=='word/document.xml': assert '\u200d'.encode() in data;data=data.replace('\u200d'.encode(),b'',1)
                target.writestr(item,data)
        path.write_bytes(buffer.getvalue())
        inputs=adaptor.read(directory,'reopen-inputs.json');inputs[str(path)]=adaptor.digest(directory,'report.docx');atomic_json(directory/'reopen-inputs.json',inputs)
        refresh(directory);report['multilingualDOCXZwjStripped']=refused(lambda:adaptor.verify(directory),reason='semantics differ')['code']
    finally:restore()
    assert adaptor.verify(directory)['verified']


# Independent literal expectations for the multilingual case (written here, not derived from the example file):
# right-to-left mark U+200F, ZWNJ U+200C, ZWJ U+200D, Thai ZWSP U+200B and England/Scotland/Wales tag-flag sequences.
def flag(code): return '\U0001f3f4'+''.join(chr(0xe0000+ord(c)) for c in code)+'\U000e007f'
MULTILINGUAL_HEADER=['Start (ms)','End (ms)','Text']
MULTILINGUAL_ROWS=[['0','1400','Hebrew: \u05e9\u05dc\u05d5\u05dd\u200f (hello), with a right-to-left mark.'],
                   ['1400','3100','Persian: \u0645\u06cc\u200c\u062e\u0648\u0627\u0647\u0645 \u06cc\u06a9 \u0686\u0627\u06cc.'],
                   ['3100','4600','Hindi: \u0915\u094d\u200d\u0937 \u0914\u0930 \u0924\u094d\u0930.'],
                   ['4600','6000','Thai: \u0e2a\u0e27\u0e31\u0e2a\u0e14\u0e35\u200b\u0e04\u0e23\u0e31\u0e1a'],
                   ['6000','7500','Flags: England '+flag('gbeng')+', Scotland '+flag('gbsct')+', Wales '+flag('gbwls')+'.']]


def multilingual_literals(directory,report):
    """Hebrew mark, Persian ZWNJ, Indic ZWJ, Thai ZWSP and emoji flags survive HTML, DOCX and fresh native readback."""
    header,body=literal_html_table((directory/'report.html').read_text(encoding='utf-8'))
    assert header==[MULTILINGUAL_HEADER] and body==MULTILINGUAL_ROWS,(header,body)
    flagged,paragraphs,rows=literal_docx_table(directory/'report.docx')
    assert flagged==[True,*[False]*len(MULTILINGUAL_ROWS)] and rows==[MULTILINGUAL_HEADER,*MULTILINGUAL_ROWS],rows
    head,tail,bodies,footers=literal_readback_table(directory/'reopened.json')
    assert head==[MULTILINGUAL_HEADER] and tail==MULTILINGUAL_ROWS and bodies==1 and footers==0,(head,tail)
    wanted=['\u200f','\u200c','\u200d','\u200b',flag('gbeng'),flag('gbsct'),flag('gbwls')]
    for label,text in (('html',' '.join(c for r in body for c in r)),('docx',' '.join(c for r in rows for c in r)),('readback',' '.join(c for r in tail for c in r))):
        assert all(w in text for w in wanted),label
    report['multilingual']={'rows':len(MULTILINGUAL_ROWS),'html':True,'docx':True,'readback':True,'characters':['U+200F','U+200C','U+200D','U+200B','tag flags']}


# Independent literal expectations for the real whisper.cpp transcript case (written here, not derived from the fixture
# loader or the adaptor): the three cues and digests of examples/schemaxis/fixtures/pandoc/segments-jfk-short.json.
ARTIFACT_HEADER=['Start (ms)','End (ms)','Text']
ARTIFACT_ROWS=[['0','5410','And so my fellow Americans, ask not what'],
               ['5410','9040','your country can do for you, ask what you'],
               ['9040','11000','can do for your country.']]
ARTIFACT_DIGESTS=('0fb466aec743b3a236655d7b29e4d3a1003bcd5230abcd4276af56b08cb4ba04',
                  '59dfb9a4acb36fe2a2affc14bacbee2920ff435cb13cc314a08c13f66ba7860e',
                  'a03779c86df3323075f5e796cb2ce5029f00ec8869eee3fdfb897afe36c6d002')


def artifact_literals(directory,report):
    """Cue text, millisecond times, machine-draft status and digests survive HTML, DOCX and fresh native readback."""
    source=(directory/'report.html').read_text(encoding='utf-8')
    header,body=literal_html_table(source)
    assert header==[ARTIFACT_HEADER] and body==ARTIFACT_ROWS,(header,body)
    flagged,paragraphs,rows=literal_docx_table(directory/'report.docx')
    assert flagged==[True,False,False,False] and rows==[ARTIFACT_HEADER,*ARTIFACT_ROWS] and all(set(p)=={1} for p in paragraphs),rows
    head,tail,bodies,footers=literal_readback_table(directory/'reopened.json')
    assert head==[ARTIFACT_HEADER] and tail==ARTIFACT_ROWS and bodies==1 and footers==0,(head,tail)
    with zipfile.ZipFile(directory/'report.docx') as archive: word=''.join(t.text or '' for t in ET.fromstring(archive.read('word/document.xml')).iter(W+'t'))
    readback=json.loads((directory/'reopened.json').read_text())['blocks']
    def text(items): return ''.join(i['c'] if i['t']=='Str' else ' ' for i in items if i['t'] in ('Str','Space'))
    paragraph=next(text(b['c']) for b in readback if b['t']=='Para' and text(b['c']).startswith('Status:'))
    for label,found in (('html',html.unescape(source)),('docx',word),('readback',paragraph)):
        for literal in ('Status: machine-draft.','a person has not reviewed it','accuracy is not certified','Language en; 3 cues; audio duration 11000 ms',
                        'Cue length target 42 characters, not enforced; 0 cues exceed it.',*ARTIFACT_DIGESTS):
            assert literal in found,(label,literal)
    captured=adaptor.read(directory,'captures.json')['transcript-0-1.json']
    assert captured['sha256']==ARTIFACT_DIGESTS[0] and captured['cues']==3 and captured['status']=='machine-draft',captured
    assert hashlib.sha256((directory/'transcript-0-1.json').read_bytes()).hexdigest()==ARTIFACT_DIGESTS[0]
    report['literalTranscriptArtifact']={'cues':3,'html':True,'docx':True,'readback':True,'provenance':True}


def artifact_negative(directory,report):
    """Refreshed-hash forgeries of the retained transcript and its publications; each names its intended reason."""
    saved={p:p.read_bytes() for p in directory.rglob('*') if p.is_file()}
    def restore():
        for p in sorted((p for p in directory.rglob('*') if p not in saved and not p.is_dir()),key=str,reverse=True): p.unlink()
        for p,data in saved.items(): p.write_bytes(data)
    def probe(label,change,reason,captures=None,hashes=True):
        try:
            change()
            if captures is not None: atomic_json(directory/'captures.json',captures(adaptor.read(directory,'captures.json')))
            if hashes: refresh(directory)
            report[label]=refused(lambda:adaptor.verify(directory),reason=reason)['code']
        finally: restore()
    def html_edit(old,new):
        def change():
            path=directory/'report.html';source=path.read_text(encoding='utf-8');assert old in source,old;path.write_text(source.replace(old,new,1),encoding='utf-8')
        return change
    def docx_edit(old,new):
        def change():
            path=directory/'report.docx';buffer=io.BytesIO()
            with zipfile.ZipFile(path) as source,zipfile.ZipFile(buffer,'w') as target:
                for item in source.infolist():
                    data=source.read(item.filename)
                    if item.filename=='word/document.xml': assert old in data,old;data=data.replace(old,new,1)
                    target.writestr(item,data)
            path.write_bytes(buffer.getvalue())
            inputs=adaptor.read(directory,'reopen-inputs.json');inputs[str(path)]=adaptor.digest(directory,'report.docx');atomic_json(directory/'reopen-inputs.json',inputs)
        return change
    captured=directory/'transcript-0-1.json'
    def forged_text():
        document=json.loads(captured.read_text(encoding='utf-8'));document['segments'][1]['text']='your country can do nothing for you';captured.write_bytes(adaptor_json(document))
    def forged_review():
        document=json.loads(captured.read_text(encoding='utf-8'));document['review']['status']='human-reviewed';captured.write_bytes(adaptor_json(document))
    def consistent(entries):
        data=captured.read_bytes();entries['transcript-0-1.json'].update(sha256=hashlib.sha256(data).hexdigest(),bytes=len(data),characters=sum(len(c['text']) for c in json.loads(data)['segments']));return entries
    probe('transcriptCaptureBytesChanged',forged_text,'captured transcript/source binding differs')
    probe('transcriptCaptureAndRecordConsistentlyForged',forged_text,'trusted AST differs',consistent)
    probe('transcriptCaptureReviewStatusInjected',forged_review,'no longer satisfies the timed-text contract')
    probe('transcriptCaptureRemoved',lambda:captured.unlink(),'select intact bounded regular evidence',hashes=False)
    probe('transcriptUndeclaredCapture',lambda:(directory/'transcript-0-9.json').write_bytes(captured.read_bytes()),'undeclared file')
    probe('transcriptCaptureRecordForged',lambda:None,'captured transcript/source binding differs',lambda e:{**e,'transcript-0-1.json':{**e['transcript-0-1.json'],'status':'human-reviewed'}})
    probe('transcriptHTMLStatusReviewed',html_edit('Status: machine-draft.','Status: human-reviewed.'),'semantics differ')
    probe('transcriptArtifactHTMLTimestamp',html_edit('<td>5410</td>','<td>5411</td>'),'semantics differ')
    probe('transcriptHTMLCueText',html_edit('your country can do for you','your country can do nothing for you'),'semantics differ')
    probe('transcriptHTMLDigest',html_edit(ARTIFACT_DIGESTS[1],'0'*64),'semantics differ')
    probe('transcriptDOCXStatusReviewed',docx_edit(b'Status: machine-draft.',b'Status: human-reviewed.'),'semantics differ')
    probe('transcriptArtifactDOCXTimestamp',docx_edit(b'>5410<',b'>5411<'),'semantics differ')
    probe('transcriptDOCXProvenanceRemoved',docx_edit(b'a person has not reviewed it and its accuracy is not certified',b'a person reviewed it'),'semantics differ')
    assert adaptor.verify(directory)['verified']


# Independent literals for a reviewed (author-declared human-corrected) transcript: written here from the retained real native draft
# (examples/schemaxis/whispercpp-corrections-fixtures/jfk-short-cues-segments.json), not produced by the whisper.cpp corrections route.
REVIEWED_ROWS=[['0','5410','And so, my fellow Americans: ask not what'],
               ['5410','9040','your country can do for you; ask what you'],
               ['9040','11000','can do for your country.']]


def reviewed_source(directory):
    draft=(ROOT/'examples/schemaxis/whispercpp-corrections-fixtures/jfk-short-cues-segments.json').read_bytes()
    assert hashlib.sha256(draft).hexdigest()==ARTIFACT_DIGESTS[0]
    document=json.loads(draft)
    for segment,row in zip(document['segments'],REVIEWED_ROWS): segment['text']=row[2]
    document['segmentation'].update(cuesOverTarget=0,statement='Recounted on the reviewed text; a target, not a guarantee.')
    document['version']='schemaxis.timedtext.reviewed/1'
    document['review']={'status':'human-corrected','accuracyCertified':False,'identityVerified':False,'statement':'A declaration by the author of the corrections; not verified.',
        'note':'Illustrative example declaration; no person reviewed this recording for it.','basis':{'version':'schemaxis.whispercpp.segments/1','sha256':ARTIFACT_DIGESTS[0],'bytes':len(draft)},
        'correctionCount':2,'correctedIndices':[0,1],'policy':json.loads(draft)['review']['policy']}
    path=directory/'reviewed-segments.json';path.write_bytes(timed_text.canonical_json(document));return path


def reviewed_acceptance(directory,locations,report):
    """A reviewed transcript through real Pandoc: literal HTML/DOCX/readback status, text and times, then refreshed-hash forgeries."""
    directory.mkdir(parents=True);path=reviewed_source(directory);digest=hashlib.sha256(path.read_bytes()).hexdigest()
    document={'version':adaptor.VERSION,'operation':'report','title':'Reviewed transcript','sections':[{'heading':'Transcript','level':1,'content':[
        {'kind':'transcript','segments':{'path':str(path),'sha256':digest}}]}]}
    run=directory/'run';result=adaptor.run(document,run,executable=locations['pandoc'],timeout=60);assert result['verified'] and adaptor.verify(run)['verified']
    source=(run/'report.html').read_text(encoding='utf-8');header,body=literal_html_table(source)
    assert header==[ARTIFACT_HEADER] and body==REVIEWED_ROWS,(header,body)
    flagged,paragraphs,rows=literal_docx_table(run/'report.docx');assert rows==[ARTIFACT_HEADER,*REVIEWED_ROWS],rows
    head,tail,bodies,footers=literal_readback_table(run/'reopened.json');assert head==[ARTIFACT_HEADER] and tail==REVIEWED_ROWS,(head,tail)
    with zipfile.ZipFile(run/'report.docx') as archive: word=''.join(t.text or '' for t in ET.fromstring(archive.read('word/document.xml')).iter(W+'t'))
    readback=json.loads((run/'reopened.json').read_text())['blocks']
    def text(items): return ''.join(i['c'] if i['t']=='Str' else ' ' for i in items if i['t'] in ('Str','Space'))
    paragraph=next(text(b['c']) for b in readback if b['t']=='Para' and text(b['c']).startswith('Status:'))
    for label,found in (('html',html.unescape(source)),('docx',word),('readback',paragraph)):
        for literal in ('Status: human-corrected, declared by the author of the corrections.','2 cues replaced by authored text (cue indexes 0, 1)',
                        'Illustrative example declaration; no person reviewed this recording for it.','not verified or certified','Language en; 3 cues; audio duration 11000 ms',
                        'machine draft SHA-256 '+ARTIFACT_DIGESTS[0],ARTIFACT_DIGESTS[1],ARTIFACT_DIGESTS[2],digest):
            assert literal in found,(label,literal)
        assert 'a person has not reviewed it' not in found and 'Status: machine-draft' not in found,label
    captured=adaptor.read(run,'captures.json')['transcript-0-0.json']
    assert (captured['status'],captured['cues'],captured['sha256'])==('human-corrected',3,digest),captured
    saved={p:p.read_bytes() for p in run.rglob('*') if p.is_file()}
    def restore():
        for q in sorted((q for q in run.rglob('*') if q not in saved and not q.is_dir()),key=str,reverse=True): q.unlink()
        for q,data in saved.items(): q.write_bytes(data)
    probes={}
    def probe(label,change,reason):
        try: change();refresh(run);probes[label]=refused(lambda:adaptor.verify(run),reason=reason)['code']
        finally: restore()
    def html_edit(old,new):
        def change():
            target=run/'report.html';text_=target.read_text(encoding='utf-8');assert old in text_,old;target.write_text(text_.replace(old,new,1),encoding='utf-8')
        return change
    def captured_edit(mutate):
        def change():
            file=run/'transcript-0-0.json';document=json.loads(file.read_text(encoding='utf-8'));mutate(document);file.write_bytes(timed_text.canonical_json(document))
        return change
    probe('reviewedCaptureStatusToMachineDraft',captured_edit(lambda d:d['review'].update(status='machine-draft')),'no longer satisfies the timed-text contract')
    probe('reviewedCaptureIdentityClaimed',captured_edit(lambda d:d['review'].update(identityVerified=True)),'no longer satisfies the timed-text contract')
    probe('reviewedCaptureCountForged',captured_edit(lambda d:d['review'].update(correctionCount=0)),'no longer satisfies the timed-text contract')
    probe('reviewedCaptureTextChanged',captured_edit(lambda d:d['segments'][0].update(text='And so, my fellow citizens: ask not what')),'or its pin')
    probe('reviewedHTMLStatusToMachineDraft',html_edit('Status: human-corrected,','Status: machine-draft,'),'semantics differ')
    probe('reviewedHTMLDisclaimerRemoved',html_edit('not verified or certified','verified'),'semantics differ')
    probe('reviewedHTMLTimestamp',html_edit('<td>5410</td>','<td>5411</td>'),'semantics differ')
    assert adaptor.verify(run)['verified']
    report['reviewedTranscript']={'status':'human-corrected','cues':3,'html':True,'docx':True,'readback':True,'forgeries':probes,'source':'literal reviewed document built here from the retained real native draft'}


def tree_digests(directory): return {str(q.relative_to(directory)):hashlib.sha256(q.read_bytes()).hexdigest() for q in sorted(directory.rglob('*')) if q.is_file()}


def legacy_acceptance(directory,locations,report,genuine=()):
    """Runs written with the earlier transcript loss sentence: genuine ones re-verify read-only; rewritten real runs verify only for machine drafts."""
    directory.mkdir(parents=True);reviewed=reviewed_source(directory)
    machine=ROOT/'examples/schemaxis/whispercpp-corrections-fixtures/jfk-short-cues-segments.json'
    def make(name,source):
        document={'version':adaptor.VERSION,'operation':'report','title':'Earlier wording','sections':[{'heading':'Transcript','level':1,'content':[
            {'kind':'transcript','segments':{'path':str(source),'sha256':hashlib.sha256(source.read_bytes()).hexdigest()}}]}]}
        run=directory/name;assert adaptor.run(document,run,executable=locations['pandoc'],timeout=60)['verified'];return run
    def rewrite(run,summary_losses=True):
        plan=adaptor.read(run,'plan.json');plan['losses'][-1]=adaptor.LEGACY_TRANSCRIPT_LOSS;atomic_json(run/'plan.json',plan)
        if summary_losses:
            summary=adaptor.read(run,'report-summary.json');assert summary['losses'][-1]==adaptor.TRANSCRIPT_LOSS;summary['losses'][-1]=adaptor.LEGACY_TRANSCRIPT_LOSS;atomic_json(run/'report-summary.json',summary)
        refresh(run)
    out={}
    run=make('machine-earlier',machine);rewrite(run);result=adaptor.verify(run)
    assert result['verified'] and result['transcripts']==1 and adaptor.read(run,'report-summary.json')['losses'][-1]==adaptor.LEGACY_TRANSCRIPT_LOSS,result
    out['machineRunWithEarlierLossAndSummary']='verified'
    run=make('machine-mixed',machine);rewrite(run,summary_losses=False)
    out['earlierPlanWithCurrentSummary']=refused(lambda:adaptor.verify(run),reason='report summary differs')['code']
    run=make('reviewed-earlier',reviewed);rewrite(run)
    out['reviewedRunWithEarlierLoss']=refused(lambda:adaptor.verify(run),reason='accepted only when every captured transcript is a machine draft')['code']
    run=make('reviewed-current',reviewed);assert adaptor.verify(run)['verified'];out['reviewedRunWithCurrentLoss']='verified'
    out['genuine']={}
    for path in genuine:
        path=Path(path).resolve();before=tree_digests(path);result=adaptor.verify(path);assert result['verified'],result;assert tree_digests(path)==before,'evidence modified'
        earlier=adaptor.read(path,'plan.json')['losses'][-1]==adaptor.LEGACY_TRANSCRIPT_LOSS
        assert earlier, f'--genuine-run must retain the earlier transcript loss wording: {path}'
        out['genuine'][path.name]={'verified':True,'transcripts':result.get('transcripts',0),'storedEarlierLoss':earlier,'evidenceUnchanged':True}
    report['earlierTranscriptWording']=out


def adaptor_json(value): return (json.dumps(value,indent=2,sort_keys=True,ensure_ascii=False)+'\n').encode('utf-8')


def artifact_lifecycle(directory,locations,document,report):
    """Source-byte reuse and faults for the transcript block, run natively through the workflow."""
    source=directory/'segments.json';shutil.copyfile(document['sections'][0]['content'][1]['segments']['path'],source)
    document['sections'][0]['content'][1]['segments']['path']=str(source)
    graph={'version':'schemaxis.workflow/1','operations':[{'id':'report','document':document}]}
    first=workflow.execute(graph,directory/'artifact-workflow',locations=locations,timeout=60);assert workflow.verify(directory/'artifact-workflow')['verified']
    resumed=workflow.execute(graph,directory/'artifact-workflow',locations=locations,timeout=60,resume=True);assert resumed['jobs'][0]['reused']
    changed=json.loads(source.read_text(encoding='utf-8'));changed['segments'][2]['text']='can do for your country, friends.';source.write_bytes(adaptor_json(changed))
    again=workflow.execute(graph,directory/'artifact-workflow',locations=locations,timeout=60,resume=True)
    assert not again['jobs'][0]['reused'] and workflow.verify(directory/'artifact-workflow')['verified']
    faults={}
    for label,code,edit in (('missing','TRANSCRIPT_SOURCE_MISSING',lambda p:p.unlink()),('invalidJson','TIMED_TEXT_INVALID_JSON',lambda p:p.write_bytes(b'And so my fellow Americans\n')),
                            ('reviewed','TIMED_TEXT_REVIEW_UNSUPPORTED',lambda p:p.write_bytes(adaptor_json({**changed,'review':{'status':'human-reviewed'}}))),
                            ('overlap','TIMED_TEXT_TIMING',lambda p:p.write_bytes(adaptor_json({**changed,'segments':[changed['segments'][0],{**changed['segments'][1],'startMs':1}, changed['segments'][2]]})))):
        edit(source);faults[label]=refused(lambda:adaptor.run(document,directory/('artifact-'+label),executable=locations['pandoc'],timeout=60),code)['code']
        assert json.loads((directory/('artifact-'+label)/'result.json').read_text())['status']=='failed'
    report['transcriptLifecycle']={'baseline':first['status'],'unchangedReused':True,'changedSourceReused':False,'faults':faults}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pandoc',required=True,type=Path)
    parser.add_argument('--output-directory',required=True,type=Path)
    parser.add_argument('--register',action='store_true',help='retain successful source-bound native qualification in adaptor package')
    parser.add_argument('--genuine-run',action='append',default=[],type=Path,help='read-only retained earlier run directory to re-verify in place (never modified)')
    parser.add_argument('--reviewed-only',action='store_true',help='run only the reviewed-transcript acceptance with real Pandoc (never registers a receipt)')
    args=parser.parse_args();directory=args.output_directory.resolve();directory.mkdir(parents=True,exist_ok=False)
    locations={'pandoc':str(args.pandoc.resolve())};report={'verified':False,'negative':{}}
    if args.reviewed_only:
        reviewed_acceptance(directory/'reviewed',locations,report);legacy_acceptance(directory/'earlier',locations,report,args.genuine_run);report['verified']=True;atomic_json(directory/'reviewed-acceptance.json',report);print(json.dumps(report,indent=2));return
    try:
        receipt=qualify(adaptor.VERSION,directory/'kit',native=True,root=ROOT,locations=locations,timeout=60,wall_timeout=90)
        report['native']={'verified':receipt['verified'],'cases':[c['id'] for c in receipt['cases']],'runtime':[c['runtime'] for c in receipt['cases']],'lifecycle':receipt['lifecycle']}
        baseline=directory/'kit/calibration-report';negative(baseline,report['negative'])
        package_negative(baseline,report['negative'])
        transcript=directory/'kit/interview-transcript';transcript_literals(transcript,report['negative']);transcript_negative(transcript,report['negative'])
        multilingual=directory/'kit/multilingual-transcript';multilingual_literals(multilingual,report['negative']);multilingual_negative(multilingual,report['negative'])
        artifact=directory/'kit/jfk-transcript-artifact';artifact_literals(artifact,report['negative']);artifact_negative(artifact,report['negative'])
        _,_,whole=route_materials(adaptor.VERSION)
        artifact_lifecycle(directory,locations,case_document(whole,next(c for c in whole['development']['cases'] if c['id']=='jfk-transcript-artifact'),ROOT),report)
        reviewed_acceptance(directory/'reviewed',locations,report['negative']);legacy_acceptance(directory/'earlier',locations,report['negative'],args.genuine_run)
        _,_,entry=route_materials(adaptor.VERSION);document=case_document(entry,entry['development']['cases'][0],ROOT)
        image=directory/'source.png';shutil.copyfile(document['sections'][1]['content'][1]['source'],image)
        document['sections'][1]['content'][1]['source']=str(image)
        graph={'version':'schemaxis.workflow/1','operations':[{'id':'report','document':document}]}
        first=workflow.execute(graph,directory/'workflow',locations=locations,timeout=60);assert workflow.verify(directory/'workflow')['verified']
        resumed=workflow.execute(graph,directory/'workflow',locations=locations,timeout=60,resume=True);assert resumed['jobs'][0]['reused']
        # Valid changed image bytes with identical pixel content still invalidate byte identity.
        data=image.read_bytes();import struct,zlib
        pos=8;parts=[]
        while pos<len(data):
            length=struct.unpack('>I',data[pos:pos+4])[0];kind=data[pos+4:pos+8];body=data[pos+8:pos+8+length]
            if kind==b'IDAT':body=zlib.compress(zlib.decompress(body),level=0)
            parts.append(struct.pack('>I',len(body))+kind+body+struct.pack('>I',zlib.crc32(kind+body)));pos+=12+length
        image.write_bytes(data[:8]+b''.join(parts));adaptor.png(image.read_bytes(),'changed image')
        changed=workflow.execute(graph,directory/'workflow',locations=locations,timeout=60,resume=True);assert not changed['jobs'][0]['reused'];assert workflow.verify(directory/'workflow')['verified']
        report['workflow']={'baseline':first['status'],'unchangedReused':True,'changedImageReused':False}
        # Shared authored bindings and a finite study exercise effective schema execution.
        study=copy.deepcopy(document);study['definitions']={'title':'Bound calibration report'};study['title']={'$document':'/definitions/title'}
        study['axes']=[{'name':'width','values':[40,70]}];study['sections'][1]['content'][1]['widthMm']={'$axis':'width'}
        result=adaptor.run(study,directory/'study',executable=locations['pandoc'],timeout=60);assert adaptor.verify(directory/'study')['verified'];assert len(result['states'])==2
        report['composition']={'states':2,'verified':True}
        # Pandoc stores byte-identical images once: two pictures after a text paragraph (BodyText style) share one media part.
        pair=copy.deepcopy(document);pair['sections']=[{'heading':'Pictures','content':[{'kind':'paragraph','text':'Before'},
            {'kind':'image','source':str(image),'alt':'First','widthMm':40},{'kind':'image','source':str(image),'alt':'Second','widthMm':60}]}]
        adaptor.run(pair,directory/'shared-media',executable=locations['pandoc'],timeout=60);assert adaptor.verify(directory/'shared-media')['images']==2
        with zipfile.ZipFile(directory/'shared-media/report.docx') as archive: report['sharedMedia']={'pictures':2,'mediaParts':len([n for n in archive.namelist() if n.startswith('word/media/')])}
        assert report['sharedMedia']['mediaParts']==1
        # Boundary widths: the largest and most precise accepted values verify in both writers; the first refused values
        # (DOCX page-width clamp, HTML five-decimal rounding) never reach Pandoc.
        bounds={}
        for label,width in (('maximum',148),('precision',12.34567)):
            sized=copy.deepcopy(document);sized['sections'][1]['content'][1]['widthMm']=width
            adaptor.run(sized,directory/('width-'+label),executable=locations['pandoc'],timeout=60);assert adaptor.verify(directory/('width-'+label))['verified'];bounds[label]=width
        for label,width in (('aboveMaximum',149),('beyondPrecision',12.3456789)):
            sized=copy.deepcopy(document);sized['sections'][1]['content'][1]['widthMm']=width
            try:adaptor.plan(sized)
            except SchemaxisError as error:bounds[label]=error.fault.code
            else:raise AssertionError('width '+str(width)+' was planned')
        report['widthBounds']=bounds
        if args.register:register(directory/'kit/qualification.json')
        report['verified']=True
    finally:atomic_json(directory/'acceptance.json',report)
    print(json.dumps(report,indent=2))


if __name__=='__main__':main()
