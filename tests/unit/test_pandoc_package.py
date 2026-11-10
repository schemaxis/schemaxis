"""Closed DOCX package: relationships, content types, fixed writer parts and picture placement."""
import hashlib
from pathlib import Path
import sys
import unittest

from schemaxis.adaptors.pandoc import inspection
from schemaxis.core.faults import SchemaxisError

sys.path.insert(0, str(Path(__file__).parent))
import pandoc_docx_fixture as fixture  # noqa: E402

W = fixture.W
REL = fixture.REL
PNG = fixture.png()
SHA = hashlib.sha256(PNG).hexdigest()
IMAGE = {'kind': 'image', 'alt': 'Alt text', 'sha256': SHA, 'widthMm': 8.0}
TEXT = {'kind': 'paragraph', 'text': 'Body text'}
HEAD = '<w:p><w:pPr><w:pStyle w:val="Title"/></w:pPr><w:r><w:t>Report</w:t></w:r></w:p>'
PARAGRAPH = '<w:p><w:r><w:t>Body text</w:t></w:r></w:p>'
CELLS = ('<w:tbl><w:tblPr/><w:tblGrid><w:gridCol w:w="1"/></w:tblGrid>'
         '<w:tr><w:trPr><w:tblHeader w:val="on"/></w:trPr><w:tc><w:tcPr/><w:p><w:pPr><w:pStyle w:val="Compact"/></w:pPr><w:r><w:t>Head</w:t></w:r>%s</w:p></w:tc></w:tr>'
         '<w:tr><w:tc><w:tcPr/><w:p><w:pPr><w:pStyle w:val="Compact"/></w:pPr><w:r><w:t>Cell</w:t></w:r></w:p></w:tc></w:tr></w:tbl>')
TABLE = {'kind': 'table', 'rows': [['Head'], ['Cell']]}
SECTION = '<w:sectPr/>'
MEDIA = {'rId11.png': PNG}


def picture(**fields): return fixture.image_paragraph(**fields)


def report(*blocks, media=None, change=None, add=None, drop=(), model=None):
    """Data and model for a Title, then the XML blocks; `media` None means a report with no pictures."""
    data = fixture.build(HEAD + ''.join(blocks) + SECTION, media=media, change=change, add=add, drop=drop)
    return data, model


class PackageCase(unittest.TestCase):
    def accepted(self, data, model):
        fixture.check(data, 'Report', model)

    def refused(self, data, model, fragment):
        with self.assertRaises(SchemaxisError) as caught: fixture.check(data, 'Report', model)
        self.assertEqual(caught.exception.fault.code, 'VERIFICATION_FAILED')
        self.assertIn(fragment, caught.exception.fault.message)


class Package(PackageCase):
    def test_reference_text_and_picture_packages_are_accepted(self):
        self.accepted(*report(PARAGRAPH, model=[TEXT]))
        self.accepted(*report(PARAGRAPH, picture(), media=MEDIA, model=[TEXT, IMAGE]))
        # Pandoc stores byte-identical images once: two pictures may share one media relationship.
        self.accepted(*report(PARAGRAPH, picture(), picture(), media=MEDIA, model=[TEXT, IMAGE, IMAGE]))
        self.accepted(*report(picture(style='BodyText'), picture(rid='rId12'), media={'rId11.png': PNG, 'rId12.png': PNG}, model=[IMAGE, IMAGE]))

    def package(self, **fields):
        return fixture.build(HEAD + PARAGRAPH + SECTION, **fields)

    def test_relationships_must_keep_each_type_and_target(self):
        rels = fixture.parts(HEAD + PARAGRAPH + SECTION)['word/_rels/document.xml.rels']
        style = b'Type="%sstyles" Id="x"' % REL.encode()
        self.assertIn(b'Target="styles.xml"', rels)
        # A second part carrying a style sheet, wired up consistently by relationship and content type.
        theme2 = b'<w:styles xmlns:w="%s"><w:style w:styleId="Compact"><w:rPr><w:vanish/></w:rPr></w:style></w:styles>' % W.encode()
        types = fixture.parts(HEAD + PARAGRAPH + SECTION)['[Content_Types].xml']
        retargeted = rels.replace(b'Target="styles.xml"', b'Target="theme/theme2.xml"')
        retyped = types.replace(b'</Types>', b'<Override PartName="/word/theme/theme2.xml" ContentType="%swordprocessingml.styles+xml"/></Types>' % fixture.OFFICE.encode())
        cases = {
            'styles relationship re-pointed with its own part and content type': (
                self.package(change={'word/_rels/document.xml.rels': retargeted, '[Content_Types].xml': retyped}, add={'word/theme/theme2.xml': theme2}),
                'relationship type or target differs'),
            'styles relationship re-pointed to the theme part': (
                self.package(change={'word/_rels/document.xml.rels': rels.replace(b'Target="styles.xml"', b'Target="theme/theme1.xml"')}),
                'relationship type or target differs'),
            'orphan theme part': (self.package(add={'word/theme/theme2.xml': theme2}), 'unexpected DOCX package member'),
            'orphan theme part with content type': (self.package(add={'word/theme/theme2.xml': theme2}, change={'[Content_Types].xml': retyped}),
                                                    'unexpected DOCX package member'),
            'duplicated relationship type': (self.package(change={'word/_rels/document.xml.rels': rels.replace(b'</Relationships>', b'<Relationship Id="y" ' + style.split(b' Id')[0] + b' Target="styles.xml"/></Relationships>')}),
                                             'relationship type or target differs'),
            'unreviewed relationship type': (self.package(change={'word/_rels/document.xml.rels': rels.replace(b'</Relationships>', b'<Relationship Id="y" Type="%sattachedTemplate" Target="styles.xml"/></Relationships>' % REL.encode())}),
                                             'unexpected DOCX relationship'),
            'media relationship without media part': (self.package(change={'word/_rels/document.xml.rels': rels.replace(b'</Relationships>', b'<Relationship Id="y" Type="%simage" Target="media/rId11.png"/></Relationships>' % REL.encode())}),
                                                      'unexpected DOCX package member'),
            'media relationship leaving the media folder': (self.package(change={'word/_rels/document.xml.rels': rels.replace(b'</Relationships>', b'<Relationship Id="y" Type="%simage" Target="../word/styles.xml"/></Relationships>' % REL.encode())}),
                                                            'unexpected DOCX relationship'),
            'explicit internal target mode': (self.package(change={'word/_rels/document.xml.rels': rels.replace(b'Target="styles.xml"', b'Target="styles.xml" TargetMode="Internal"')}),
                                              'unexpected DOCX relationship element'),
            'package root relationship dropped': (self.package(change={'_rels/.rels': fixture.relationships([('rId1', REL + 'officeDocument', 'word/document.xml')])}),
                                                  'relationship set differs'),
            'package root points at another document': (self.package(change={'_rels/.rels': fixture.parts('')['_rels/.rels'].replace(b'word/document.xml', b'word/theme/theme1.xml')}),
                                                        'relationship type or target differs'),
            'duplicate relationship id': (self.package(change={'word/_rels/document.xml.rels': rels.replace(b'Id="rId2"', b'Id="rId1"')}), 'duplicate DOCX relationship id')}
        for label, (data, fragment) in cases.items():
            with self.subTest(label): self.refused(data, [TEXT], fragment)

    def test_unmapped_layout_and_crop_controls_are_refused(self):
        self.refused(fixture.build(HEAD + (CELLS % '').replace('<w:tblPr/>','<w:tblPr><w:tblpPr w:tblpX="-999999"/></w:tblPr>') + SECTION),[TABLE],'table layout properties')
        self.refused(fixture.build(HEAD + PARAGRAPH + '<w:sectPr><w:pgSz w:w="0" w:h="0"/></w:sectPr>'),[TEXT],'section layout properties')
        hidden=picture().replace('<wp:docPr ','<wp:docPr hidden="1" ')
        self.refused(fixture.build(HEAD + hidden + SECTION,media=MEDIA),[IMAGE],'image properties')
        crop=picture().replace('<a:stretch>','<a:srcRect l="100000"/><a:stretch>')
        self.refused(fixture.build(HEAD + crop + SECTION,media=MEDIA),[IMAGE],'image fill or crop')

    def test_content_types_are_exact(self):
        types = fixture.parts(HEAD + PARAGRAPH + SECTION)['[Content_Types].xml']
        document_type = b'wordprocessingml.document.main+xml'
        cases = {
            'document typed as a macro-enabled document': (types.replace(document_type, b'wordprocessingml.document.macroEnabled.main+xml'), 'content type overrides differ'),
            'styles override dropped': (types.replace(b'<Override PartName="/word/styles.xml" ContentType="%swordprocessingml.styles+xml"/>' % fixture.OFFICE.encode(), b''),
                                        'content type overrides differ'),
            'extra override': (types.replace(b'</Types>', b'<Override PartName="/word/header1.xml" ContentType="x/y"/></Types>'), 'content type overrides differ'),
            'default for png added': (types.replace(b'</Types>', b'<Default Extension="png" ContentType="image/png"/></Types>'), 'default content types differ'),
            'default xml retyped': (types.replace(b'application/xml', b'text/html', 1), 'default content types differ'),
            'unknown entry': (types.replace(b'</Types>', b'<Foo/></Types>'), 'unexpected DOCX content type entry'),
            'duplicate override': (types.replace(b'</Types>', b'<Override PartName="/word/styles.xml" ContentType="%swordprocessingml.styles+xml"/></Types>' % fixture.OFFICE.encode()),
                                   'duplicate DOCX content type override')}
        for label, (change, fragment) in cases.items():
            with self.subTest(label): self.refused(fixture.build(HEAD + PARAGRAPH + SECTION, change={'[Content_Types].xml': change}), [TEXT], fragment)

    def test_media_content_type_must_be_png(self):
        types = fixture.parts(HEAD + picture() + SECTION, media=MEDIA)['[Content_Types].xml']
        data = fixture.build(HEAD + picture() + SECTION, media=MEDIA, change={'[Content_Types].xml': types.replace(b'image/png', b'image/svg+xml')})
        self.refused(data, [IMAGE], 'content type overrides differ')

    def test_every_fixed_writer_part_is_bound_to_its_reviewed_bytes(self):
        for name in inspection.DOCX_FIXED_PARTS:
            with self.subTest(name):
                self.refused(self.package(change={name: fixture.FIXED[name] + b'<!-- edited -->'}), [TEXT], 'differs from qualified Pandoc')

    def test_theme_edit_cannot_change_fonts_or_colours(self):
        theme = b'<a:theme xmlns:a="x"><a:minorFont><a:latin typeface="Wingdings"/></a:minorFont><a:accent1><a:srgbClr val="FFFFFF"/></a:accent1></a:theme>'
        self.refused(self.package(change={'word/theme/theme1.xml': theme}), [TEXT], 'word/theme/theme1.xml differs')

    def test_core_properties_hold_only_the_report_title(self):
        core = fixture.core('Report')
        cases = {'different title': core.replace(b'>Report<', b'>Something else<'), 'creator added': core.replace(b'<dc:creator></dc:creator>', b'<dc:creator>FAKE</dc:creator>'),
                 'keywords added': core.replace(b'<cp:keywords></cp:keywords>', b'<cp:keywords>FAKE</cp:keywords>'),
                 'element dropped': core.replace(b'<cp:keywords></cp:keywords>', b''), 'date text': core.replace(b'1970-01-01T00:00:00Z', b'FAKE', 1)}
        for label, data in cases.items():
            with self.subTest(label): self.refused(self.package(change={'docProps/core.xml': data}), [TEXT], 'core properties differ')


class Pictures(PackageCase):
    def test_forged_picture_shapes_are_refused_with_their_reason(self):
        anchor = picture(shape='anchor')
        cases = {
            'anchored floating picture': (anchor, 'unsupported DOCX inline/control: anchor'),
            'blip with transparency child': (picture(blip='<a:blip r:embed="%s"><a:alphaModFix amt="0"/></a:blip>'), 'one plain blip'),
            'blip with extra relationship attribute': (picture(blip='<a:blip r:embed="%s" r:link="rId11"/>'), 'relationship reference'),
            'two blips': (picture(blip='<a:blip r:embed="%s"/><a:blip r:embed="%s"/>'.replace('%s', 'rId11')), 'one plain blip'),
            'unreviewed style': (picture(style='Heading1'), 'drawing outside a declared image paragraph'),
            'extra run': (picture().replace('</w:r></w:p>', '</w:r><w:r><w:t>hidden</w:t></w:r></w:p>'), 'image paragraph structure differs'),
            'text beside the drawing': (picture().replace('<w:drawing>', '<w:t>x</w:t><w:drawing>'), 'exactly one drawing'),
            'second drawing in the run': (picture().replace('</w:drawing></w:r>', '</w:drawing><w:drawing/></w:r>'), 'exactly one drawing'),
            'second graphic in the inline picture': (picture().replace('</wp:inline>', '<a:graphic/></wp:inline>'), 'inline drawing structure differs')}
        for label, (xml, fragment) in cases.items():
            with self.subTest(label): self.refused(*report(xml, media=MEDIA, model=[IMAGE]), fragment)

    def test_drawings_are_refused_outside_declared_image_paragraphs(self):
        drawing = picture()[len('<w:p><w:pPr><w:pStyle w:val="FirstParagraph"/></w:pPr>'):-len('</w:p>')]
        cases = {
            'text paragraph': ('<w:p><w:r><w:t>Body text</w:t></w:r>' + drawing + '</w:p>', [TEXT], 'drawing outside a declared image paragraph'),
            'table cell': (CELLS % drawing, [TABLE], 'unexpected DOCX run content'),
            'title paragraph': (None, [TEXT], 'drawing outside a declared image paragraph'),
            'image paragraph where text is declared': (picture(), [TEXT], 'drawing outside a declared image paragraph'),
            'floating shape in a table cell': (CELLS % picture(shape='anchor')[picture().index('<w:r>'):-len('</w:p>')], [TABLE], 'unsupported DOCX inline/control: anchor')}
        for label, (xml, model, fragment) in cases.items():
            with self.subTest(label):
                if xml is None: data = fixture.build(HEAD.replace('<w:r><w:t>Report</w:t></w:r>', '<w:r><w:t>Report</w:t></w:r>' + drawing) + SECTION, media=MEDIA)
                else: data = fixture.build(HEAD + xml + SECTION, media=MEDIA)
                self.refused(data, model, fragment)

    def test_picture_counts_cover_the_whole_document(self):
        drawing = picture()[len('<w:p><w:pPr><w:pStyle w:val="FirstParagraph"/></w:pPr>'):-len('</w:p>')]
        # A second picture reusing the declared image's relationship id in a cell would pass a media-membership check alone.
        cell = fixture.build(HEAD + picture() + CELLS % drawing + SECTION, media=MEDIA)
        self.refused(cell, [IMAGE, TABLE], 'unexpected DOCX run content')
        hidden = fixture.build(HEAD + picture() + '<w:sectPr><w:drawing/></w:sectPr>', media=MEDIA)
        self.refused(hidden, [IMAGE], 'DOCX section layout properties')
        self.refused(*report(picture(), media={'rId11.png': PNG, 'rId12.png': PNG}, model=[IMAGE]), 'undeclared media membership differs')
        self.refused(*report(picture(), media=MEDIA, model=[IMAGE, IMAGE]), 'picture count differs')

    def test_relationship_references_outside_pictures_are_refused(self):
        linked = '<w:p><w:r><w:t xml:space="preserve" r:id="rId11">Body text</w:t></w:r></w:p>'
        self.refused(*report(linked, media=MEDIA, model=[TEXT]), 'relationship reference')

    def test_picture_geometry_and_pixels_stay_bound(self):
        self.refused(*report(picture(cx=999999), media=MEDIA, model=[IMAGE]), 'width differs')
        self.refused(*report(picture(cy=999999), media=MEDIA, model=[IMAGE]), 'aspect ratio differs')
        self.refused(*report(picture(), media={'rId11.png': fixture.png(shade=9)}, model=[IMAGE]), 'ordered heading')


if __name__ == '__main__': unittest.main()
